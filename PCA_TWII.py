# -*- coding: utf-8 -*-
"""
V13.4 PCA_TWII.py (跨表對齊版)
- 架構更新：總經特徵 (X) 與個股目標 (Y) 跨表分離架構。
- PRE_TWII 來自 global_market_factors。
- 其他 13 檔股票來自 stock_history_13_targets。
- 自動透過 Date Index 執行 Inner Join，解決台美股休假日不同步的問題。
"""
import os
import sys
import subprocess
import importlib
from datetime import datetime
import json
import time
import traceback
import re
import pandas as pd
import numpy as np

# --- 參數設定 ---
DATA_LAKE_URL = ""  # (選填) 如果有 global_market_factors 的獨立網址可以填這
STOCK_HISTORY_URL = "" # (選填) 如果有 stock_history_13_targets 的獨立網址可以填這

TARGET_SPREADSHEETS = {
    "PRE_TWII": "",         
    "PRE_台積電(2330)": "",
    "PRE_聯電(2303)": "",
    "PRE_英業達(2356)": "",
    "PRE_中鋼(2002)": "",
    "PRE_NVIDIA(NVDA)": "",
    "PRE_TESLA(TSLA)": "",
    "PRE_INTEL(INTC)": "",
    "PRE_Apple(AAPL)": "",
    "PRE_Microsoft(MSFT)": "",
    "PRE_Amazon(AMZN)": "",
    "PRE_Eli Lilly(LLY)": "",
    "PRE_Novo Nordisk(NVO)": "",
    "PRE_Toyota(7203.T)": ""
}

def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動環境檢查...")
    dependencies = {
        "pandas": "pandas", "numpy": "numpy", "sklearn": "scikit-learn",
        "xgboost": "xgboost", "gspread": "gspread", "google.oauth2.service_account": "google-auth"
    }
    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            installed_any = True
    if installed_any:
        importlib.invalidate_caches()

bootstrap()

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from xgboost import XGBRegressor
import gspread
from google.oauth2.service_account import Credentials

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(creds)

def safe_gspread_write(gc, sp_id, tab_name, df, mode="append"):
    for attempt in range(3):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=tab_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            df = df.fillna("")
            new_headers = df.columns.values.tolist()
            
            if mode == "clear_update":
                data = [new_headers] + df.values.tolist()
                worksheet.clear()
                worksheet.update(values=data, range_name=None)
            elif mode == "append":
                existing_data = worksheet.get_all_values()
                if not existing_data:
                    worksheet.append_row(new_headers)
                elif existing_data[0] != new_headers:
                    worksheet.clear()
                    worksheet.append_row(new_headers)
                worksheet.append_rows(df.values.tolist())
            return True
        except Exception as e:
            time.sleep(2)
    return False

def load_sheet_as_dataframe(sh, worksheet_name=None):
    """將指定的 Google Sheet 分頁轉換為 DataFrame (Date 為 Index)"""
    try:
        if worksheet_name:
            ws = sh.worksheet(worksheet_name)
        else:
            ws = sh.get_worksheet(0) # 沒指定則抓第一個分頁
    except Exception as e:
        raise ValueError(f"找不到分頁: {worksheet_name if worksheet_name else '第一個分頁'}。錯誤: {e}")
        
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    
    if 'Date' not in df.columns:
        if '日期' in df.columns:
            df.rename(columns={'日期': 'Date'}, inplace=True)
        else:
            df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
    
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df.dropna(subset=['Date'], inplace=True) # 移除無效日期
    df.set_index('Date', inplace=True)
    df = df.replace("", np.nan).apply(pd.to_numeric, errors='coerce').ffill() 
    df.dropna(axis=1, how='all', inplace=True)
    df.sort_index(inplace=True)
    return df

def find_spreadsheet(gc, file_name, file_url=""):
    if file_url.strip():
        try: return gc.open_by_url(file_url.strip())
        except Exception: pass
    for f in gc.list_spreadsheet_files():
        if f.get('name') == file_name: return gc.open_by_key(f['id'])
    return None

def identify_target_column(df, file_name):
    """
    🎯 智能拆解搜尋：拆解中文名與代碼，增加命中率
    """
    candidates = []
    if "TWII" in file_name:
        candidates = ["^twii", "twii", "加權指數", "大盤"]
    else:
        match = re.search(r'PRE_(.*?)\((.*?)\)', file_name)
        if match:
            name = match.group(1).strip()
            ticker = match.group(2).strip()
            if name: candidates.append(name)
            if ticker: candidates.append(ticker)
        else:
            candidates.append(file_name.replace("PRE_", ""))
            
    # 階段 1：嚴格匹配 -> 包含代碼/名稱，且包含 Close 或 收盤
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and ("close" in col_lower or "收盤" in col_lower):
                return col
                
    # 階段 2：寬鬆匹配 -> 包含代碼/名稱，且「沒有」Volume 或 成交量
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and "volume" not in col_lower and "成交量" not in col_lower:
                return col
                
    return None

def predict_with_layered_arena(df_X, s_y):
    """
    將 特徵(X) 與 目標(Y) 進行日期對齊 (Inner Join)，再進行訓練。
    這可解決 X 和 Y 來自不同檔案，休假日不一致的問題。
    """
    # 將 Y Series 命名確保一致
    s_y.name = "Target_Close"
    
    # 根據 Date (Index) 進行內部合併，確保 X 都有對應的 Y
    aligned_data = pd.concat([df_X, s_y], axis=1, join='inner').dropna()
    
    if len(aligned_data) < 100: 
        return None, None
    
    # 拆分回對齊後的 X 和 Y
    y_raw = aligned_data["Target_Close"]
    df_aligned_X = aligned_data.drop(columns=["Target_Close"])
    
    # --- PCA 降維處理 ---
    scaler = StandardScaler()
    X_scaled_np = scaler.fit_transform(df_aligned_X)
    df_X_scaled = pd.DataFrame(X_scaled_np, index=df_aligned_X.index, columns=df_aligned_X.columns)
    
    pca = PCA(n_components=min(5, len(df_aligned_X.columns)))
    X_pca_np = pca.fit_transform(X_scaled_np)
    df_X_pca = pd.DataFrame(X_pca_np, index=df_aligned_X.index, columns=[f"PC{i+1}" for i in range(pca.n_components_)])
    
    # 用於後續位移計算的整合表
    merged_for_shift = pd.concat([df_X_scaled, df_X_pca, y_raw], axis=1)

    model_names = ['PCA_Poly_Ridge', 'RandomForest', 'XGBoost']
    model_preds = {m: {} for m in model_names}
    model_rmse = {m: {} for m in model_names} 
    
    for window_name, shift_days in WINDOWS.items():
        # 目標 Y 是未來 shift_days 的漲跌幅
        y_target = merged_for_shift["Target_Close"].pct_change(shift_days).shift(-shift_days) * 100
        valid_idx = ~y_target.isna()
        
        if valid_idx.sum() < 60:
            for m in model_names: 
                model_preds[m][window_name] = "N/A"
                model_rmse[m][window_name] = None
            continue
            
        X_raw_v = merged_for_shift[df_aligned_X.columns].values[valid_idx]
        X_pca_v = merged_for_shift[[f"PC{i+1}" for i in range(pca.n_components_)]].values[valid_idx]
        Y_v = y_target[valid_idx].values
        
        split_idx = int(len(Y_v) * 0.8)
        
        X_latest_raw = merged_for_shift[df_aligned_X.columns].values[-1].reshape(1, -1)
        X_latest_pca = merged_for_shift[[f"PC{i+1}" for i in range(pca.n_components_)]].values[-1].reshape(1, -1)
        
        # 1. PCA + 多項式 + 嶺回歸
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_pca_poly = poly.fit_transform(X_pca_v[:split_idx])
        X_test_pca_poly = poly.transform(X_pca_v[split_idx:])
        
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train_pca_poly, Y_v[:split_idx])
        r_preds_test = ridge.predict(X_test_pca_poly)
        model_rmse['PCA_Poly_Ridge'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], r_preds_test)))
        model_preds['PCA_Poly_Ridge'][window_name] = round(float(ridge.predict(poly.transform(X_latest_pca))[0]), 2)
        
        # 2. Random Forest (使用原始對齊特徵)
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        rf_preds_test = rf.predict(X_raw_v[split_idx:])
        model_rmse['RandomForest'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], rf_preds_test)))
        model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_raw)[0]), 2)
        
        # 3. XGBoost (使用原始對齊特徵)
        xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror')
        xgb.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        xgb_preds_test = xgb.predict(X_raw_v[split_idx:])
        model_rmse['XGBoost'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], xgb_preds_test)))
        model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_raw)[0]), 2)

    layers = list(WINDOWS.keys()) + ['Overall']
    for m in model_names:
        valid_rmses = [rmse for w, rmse in model_rmse[m].items() if rmse is not None]
        model_rmse[m]['Overall'] = float(np.mean(valid_rmses)) if valid_rmses else None

    model_ranks = {m: {} for m in model_names}
    for layer in layers:
        sorted_models = sorted(model_names, key=lambda m: model_rmse[m].get(layer) if model_rmse[m].get(layer) is not None else 9999.99)
        for rank, m in enumerate(sorted_models, 1):
            model_ranks[m][layer] = rank

    results = {}
    for m in model_names:
        results[m] = {'Preds': model_preds[m], 'RMSE': model_rmse[m], 'Ranks': model_ranks[m]}
        
    return results, df_X_pca

def main():
    print("="*70)
    print("🏆 PCA x 機器學習 (雙表架構對齊版 V13.4)")
    print("="*70)
    
    try:
        gc = get_gspread_client()
        
        # 步驟 1: 讀取總經特徵 (Data Lake)
        print("\n步驟 1: 尋找並載入總經資料 (global_market_factors)...")
        lake_sh = None
        for f in gc.list_spreadsheet_files():
            try:
                temp_sh = gc.open_by_key(f['id'])
                temp_sh.worksheet("global_market_factors")
                lake_sh = temp_sh
                break
            except Exception:
                continue
        if not lake_sh: raise ValueError("找不到含有 'global_market_factors' 的 Data Lake 檔案！")
        df_lake = load_sheet_as_dataframe(lake_sh, "global_market_factors")
        print(f"   ✅ 成功載入！特徵總數: {len(df_lake.columns)}, 歷史天數: {len(df_lake)}")

        # 步驟 2: 讀取 13 檔個股目標 (stock_history_13_targets)
        print("\n步驟 2: 尋找並載入個股歷史資料 (stock_history_13_targets)...")
        stock_sh = find_spreadsheet(gc, "stock_history_13_targets", STOCK_HISTORY_URL)
        if not stock_sh:
            print("   ⚠️ 找不到 'stock_history_13_targets'！請確認檔案名稱完全符合。")
            raise ValueError("找不到個股目標檔案")
        df_stocks = load_sheet_as_dataframe(stock_sh) # 預設讀取第一個分頁
        print(f"   ✅ 成功載入！目標股欄位數: {len(df_stocks.columns)}, 歷史天數: {len(df_stocks)}")
        
        # 顯示兩邊欄位供除錯
        print(f"\n   [除錯] df_lake 欄位預覽: {list(df_lake.columns)[:5]}...")
        print(f"   [除錯] df_stocks 欄位預覽: {list(df_stocks.columns)[:5]}...")

        # 步驟 3: 循環目標並進行訓練
        print(f"\n🎯 步驟 3: 啟動跨表對齊與預測...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        first_run_pca = None
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉 處理標的: {file_name}")
            
            # 開啟該檔股票的獨立預測檔案 (準備寫入結果)
            dest_sh = find_spreadsheet(gc, file_name, file_url)
            if not dest_sh:
                print(f"   ❌ 找不到獨立寫入試算表 [{file_name}]，跳過。")
                continue
            
            # --- 判斷資料來源與特徵對齊 ---
            df_X = df_lake.copy() # X 永遠來自總經表
            
            if file_name == "PRE_TWII":
                # TWII 的目標在 df_lake
                target_col = identify_target_column(df_lake, file_name)
                if not target_col:
                    print(f"   ⚠️ 在 global_market_factors 中找不到 TWII 欄位，跳過！")
                    continue
                s_y = df_lake[target_col].copy()
                
            else:
                # 其他 13 檔股票的目標在 df_stocks
                target_col = identify_target_column(df_stocks, file_name)
                if not target_col:
                    print(f"   ⚠️ 在 stock_history_13_targets 中找不到 '{file_name}' 的匹配欄位，跳過！")
                    continue
                s_y = df_stocks[target_col].copy()
                
            print(f"   🔍 對齊準備: X(總經特徵) + Y(目標: {target_col})")
            
            # 傳入模型進行對齊(Inner Join)與預測
            result, df_pca_features = predict_with_layered_arena(df_X, s_y)
            
            if not result:
                print(f"   ⚠️ 資料合併後天數不足，無法預測，跳過。")
                continue
                
            if first_run_pca is None: first_run_pca = df_pca_features
            
            # 排序與寫入
            sorted_model_names = sorted(result.keys(), key=lambda m: result[m]['Ranks'].get('Overall', 99))
            rows_to_add = []
            for m in sorted_model_names:
                res = result[m]
                def get_val(d, k, default="N/A", is_round=True):
                    val = d.get(k)
                    if val is None: return default
                    return round(val, 2) if is_round else val
                
                rows_to_add.append({
                    "Date": today_str, "Model_Name": m,
                    "Overall_Rank": get_val(res['Ranks'], 'Overall', is_round=False), "Overall_RMSE": get_val(res['RMSE'], 'Overall'),
                    "3D_Rank": get_val(res['Ranks'], '3day', is_round=False), "3D_RMSE": get_val(res['RMSE'], '3day'), "3_Days_Pred(%)": get_val(res['Preds'], '3day'),
                    "7D_Rank": get_val(res['Ranks'], '7day', is_round=False), "7D_RMSE": get_val(res['RMSE'], '7day'), "7_Days_Pred(%)": get_val(res['Preds'], '7day'),
                    "1M_Rank": get_val(res['Ranks'], '1month', is_round=False), "1M_RMSE": get_val(res['RMSE'], '1month'), "1_Month_Pred(%)": get_val(res['Preds'], '1month'),
                    "1Y_Rank": get_val(res['Ranks'], '1year', is_round=False), "1Y_RMSE": get_val(res['RMSE'], '1year'), "1_Year_Pred(%)": get_val(res['Preds'], '1year'),
                    "Status": "Success", "Update_Time": datetime.now().strftime("%H:%M:%S")
                })
            
            df_rows = pd.DataFrame(rows_to_add)
            if safe_gspread_write(gc, dest_sh.id, "預測紀錄", df_rows, mode="append"):
                print(f"   ✅ 成功對齊並寫入預測結果")

        # 寫出 PCA 特徵留底
        if first_run_pca is not None:
            df_pca_output = first_run_pca.reset_index()
            df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
            safe_gspread_write(gc, lake_sh.id, "global_pca_features", df_pca_output, mode="clear_update")
            
        print("\n✅ 所有獨立檔案更新完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()

if __name__ == "__main__":
    main()
