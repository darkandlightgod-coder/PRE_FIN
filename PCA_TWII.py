# -*- coding: utf-8 -*-
"""
V13.1 PCA_TWII.py (多模型競技場 - 5層獨立評估 + 無爬蟲純淨版)
完全移除 yfinance 依賴，直接從 Data Lake (rawdata) 中動態抓取對應的目標欄位。
提升穩定度、執行速度，並確保特徵與目標數值日期完美對齊。
"""
import os
import sys
import subprocess
import importlib
from datetime import datetime

# ==========================================
# 【設定區：資料湖與獨立檔案網址】
# ==========================================
DATA_LAKE_URL = "" 

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

# ==========================================
# 【環境自癒與延遲載入】(移除了 yfinance)
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動環境檢查 (包含進階機器學習套件)...")
    dependencies = {
        "pandas": "pandas",
        "numpy": "numpy",
        "sklearn": "scikit-learn",
        "xgboost": "xgboost",           
        "gspread": "gspread",
        "google.oauth2.service_account": "google-auth"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 自動安裝: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 套件自動補齊完成！\n")

bootstrap()

import json
import time
import traceback
import re
import pandas as pd
import numpy as np
from datetime import timedelta

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from xgboost import XGBRegressor

import gspread
from google.oauth2.service_account import Credentials

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

# ==========================================
# Google Sheets 工具函數
# ==========================================
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
    max_retries = 3
    for attempt in range(max_retries):
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
                    print("     🧹 偵測到欄位格式變更 (更新為 5 層評估版)，清空並覆寫新標題...")
                    worksheet.clear()
                    worksheet.append_row(new_headers)
                
                worksheet.append_rows(df.values.tolist())
                
            return True
        except Exception as e:
            time.sleep(2)
    return False

def load_data_lake(sh):
    try:
        ws = sh.worksheet("global_market_factors")
    except gspread.exceptions.WorksheetNotFound:
        raise ValueError(f"在試算表 '{sh.title}' 中找不到 'global_market_factors' 分頁！")
        
    data = ws.get_all_values()
    if not data or len(data) < 2:
        raise ValueError("分頁 'global_market_factors' 沒有資料或只有標題！")
        
    df = pd.DataFrame(data[1:], columns=data[0])
    
    if 'Date' not in df.columns:
        if '日期' in df.columns:
            df.rename(columns={'日期': 'Date'}, inplace=True)
        else:
            first_col = df.columns[0]
            df.rename(columns={first_col: 'Date'}, inplace=True)
    
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    df = df.apply(pd.to_numeric, errors='coerce')
    df = df.ffill().bfill() 
    df.dropna(axis=1, how='all', inplace=True)
    
    # 按照時間由舊到新排序，確保 shift 時序正確
    df.sort_index(inplace=True)
    
    if df.empty: raise ValueError("資料清洗後變成完全空值！")
    return df

def find_independent_spreadsheet(gc, file_name, file_url):
    if file_url.strip():
        try:
            return gc.open_by_url(file_url.strip())
        except Exception:
            return None
    for f in gc.list_spreadsheet_files():
        if f.get('name') == file_name:
            return gc.open_by_key(f['id'])
    return None

def identify_target_column(df, file_name):
    """
    從 Data Lake 的欄位中，智慧尋找對應的目標欄位 (例如: 從 'PRE_台積電(2330)' 找出包含 '2330' 或 '台積電' 的欄位)
    """
    candidates = []
    if "TWII" in file_name:
        candidates = ["^TWII", "TWII", "加權指數", "大盤"]
    else:
        # 提取括號內的代碼，如 2330, NVDA
        match = re.search(r'\((.*?)\)', file_name)
        if match:
            candidates.append(match.group(1))
        # 提取去掉 PRE_ 的名稱，如 台積電
        candidates.append(file_name.replace("PRE_", ""))
        
    for col in df.columns:
        for cand in candidates:
            # 不分大小寫比對，只要特徵欄位名稱包含該代碼/名稱即視為命中
            if cand.lower() in str(col).lower():
                return col
    return None

# ==========================================
# 🚀 核心：5層矩陣競技與評估 (Layered Model Arena)
# ==========================================
def predict_with_layered_arena(df_lake, target_col):
    # 1. 建立特徵 (Features)
    scaler = StandardScaler()
    X_scaled_np = scaler.fit_transform(df_lake)
    df_X_scaled = pd.DataFrame(X_scaled_np, index=df_lake.index, columns=df_lake.columns)
    
    pca = PCA(n_components=5)
    X_pca_np = pca.fit_transform(X_scaled_np)
    df_X_pca = pd.DataFrame(X_pca_np, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)])
    
    # 2. 直接從 Data Lake 取出目標欄位當作 y_raw (無須透過 yfinance)
    y_raw = df_lake[target_col]
    
    aligned_data = pd.concat([df_X_scaled, df_X_pca, y_raw.rename("Close")], axis=1).dropna()
    if aligned_data.empty: return None

    model_names = ['PCA_Poly_Ridge', 'RandomForest', 'XGBoost']
    
    # 資料容器：以模型為 Key，記錄每個 window 的 Pred 與 RMSE
    model_preds = {m: {} for m in model_names}
    model_rmse = {m: {} for m in model_names} 
    
    for window_name, shift_days in WINDOWS.items():
        # 計算未來 N 天的漲跌幅 (%) 作為預測目標
        y_target = aligned_data["Close"].pct_change(shift_days).shift(-shift_days) * 100
        valid_idx = ~y_target.isna()
        
        if valid_idx.sum() < 60:
            for m in model_names: 
                model_preds[m][window_name] = "N/A"
                model_rmse[m][window_name] = None
            continue
            
        X_raw_v = aligned_data[df_lake.columns].values[valid_idx]
        X_pca_v = aligned_data[[f"PC{i+1}" for i in range(5)]].values[valid_idx]
        Y_v = y_target[valid_idx].values
        
        split_idx = int(len(Y_v) * 0.8)
        
        # 準備最後一筆資料做為「明日起算」的預測基準
        X_latest_raw = aligned_data[df_lake.columns].values[-1].reshape(1, -1)
        X_latest_pca = aligned_data[[f"PC{i+1}" for i in range(5)]].values[-1].reshape(1, -1)
        
        # --- 獨立層級模型 1: PCA + Polynomial + Ridge ---
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_pca_poly = poly.fit_transform(X_pca_v[:split_idx])
        X_test_pca_poly = poly.transform(X_pca_v[split_idx:])
        
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train_pca_poly, Y_v[:split_idx])
        r_preds_test = ridge.predict(X_test_pca_poly)
        model_rmse['PCA_Poly_Ridge'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], r_preds_test)))
        model_preds['PCA_Poly_Ridge'][window_name] = round(float(ridge.predict(poly.transform(X_latest_pca))[0]), 2)
        
        # --- 獨立層級模型 2: Random Forest ---
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        rf_preds_test = rf.predict(X_raw_v[split_idx:])
        model_rmse['RandomForest'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], rf_preds_test)))
        model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_raw)[0]), 2)
        
        # --- 獨立層級模型 3: XGBoost ---
        xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror')
        xgb.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        xgb_preds_test = xgb.predict(X_raw_v[split_idx:])
        model_rmse['XGBoost'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], xgb_preds_test)))
        model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_raw)[0]), 2)

    # ----------------------------------------------------
    # 計算第五層 (Overall / 所有資料綜合誤差)
    # ----------------------------------------------------
    layers = list(WINDOWS.keys()) + ['Overall']
    
    for m in model_names:
        # 取出該模型所有合法的各層 RMSE
        valid_rmses = [rmse for w, rmse in model_rmse[m].items() if rmse is not None]
        if valid_rmses:
            model_rmse[m]['Overall'] = float(np.mean(valid_rmses))
        else:
            model_rmse[m]['Overall'] = None

    # ----------------------------------------------------
    # 進行各層獨立排序 (Ranking)
    # ----------------------------------------------------
    model_ranks = {m: {} for m in model_names}
    
    for layer in layers:
        # 將模型依照該層的 RMSE 排序 (排除 None 的情況)，RMSE 越小越前
        sorted_models = sorted(
            model_names, 
            key=lambda m: model_rmse[m].get(layer) if model_rmse[m].get(layer) is not None else 9999.99
        )
        
        for rank, m in enumerate(sorted_models, 1):
            model_ranks[m][layer] = rank

    # 整理為回傳結構
    results = {}
    for m in model_names:
        results[m] = {
            'Preds': model_preds[m],
            'RMSE': model_rmse[m],
            'Ranks': model_ranks[m]
        }
        
    return results, df_X_pca

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*60)
    print("🏆 PCA x 機器學習 (5 層矩陣獨立評估 + 無爬蟲純淨版)")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        lake_sh = None
        
        print("\n步驟 1: 載入 Data Lake (rawdata)...")
        if DATA_LAKE_URL.strip():
            lake_sh = gc.open_by_url(DATA_LAKE_URL.strip())
        else:
            for f in gc.list_spreadsheet_files():
                try:
                    temp_sh = gc.open_by_key(f['id'])
                    temp_sh.worksheet("global_market_factors")
                    lake_sh = temp_sh
                    break
                except Exception:
                    continue
                    
        if not lake_sh: raise ValueError("找不到 Data Lake！")
            
        df_lake = load_data_lake(lake_sh)
        print(f"   ✅ 成功載入特徵與歷史股價，資料筆數: {len(df_lake)}")
        
        print(f"\n🎯 步驟 2: 啟動多模型分層預測與跨檔案寫入...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        first_run_pca = None
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉 處理標的: {file_name}")
            
            target_sh = find_independent_spreadsheet(gc, file_name, file_url)
            if not target_sh:
                print(f"   ❌ 找不到目標獨立試算表。")
                continue
                
            # 🔍 從 Data Lake 找出這檔股票對應的欄位名稱
            target_col = identify_target_column(df_lake, file_name)
            if not target_col: 
                print(f"   ⚠️ 在 Data Lake 中找不到與 '{file_name}' 匹配的欄位，跳過！")
                continue
                
            print(f"   🔍 鎖定 Data Lake 目標欄位: [{target_col}]")
            
            result = predict_with_layered_arena(df_lake, target_col)
            if not result:
                print(f"   ⚠️ 資料計算後不足，跳過。")
                continue
                
            layered_results, df_pca_features = result
            if first_run_pca is None: first_run_pca = df_pca_features
            
            # 依照「第五層 (Overall)」的綜合排名，決定輸出的順序 (綜合最強的在最上面)
            sorted_model_names = sorted(layered_results.keys(), key=lambda m: layered_results[m]['Ranks'].get('Overall', 99))
            
            rows_to_add = []
            for m in sorted_model_names:
                res = layered_results[m]
                
                def get_val(d, k, default="N/A", is_round=True):
                    val = d.get(k)
                    if val is None: return default
                    return round(val, 2) if is_round else val
                
                rows_to_add.append({
                    "Date": today_str,
                    "Model_Name": m,
                    # 第五層: Overall (綜合所有資料)
                    "Overall_Rank": get_val(res['Ranks'], 'Overall', is_round=False),
                    "Overall_RMSE": get_val(res['RMSE'], 'Overall'),
                    # 第一層: 3 天
                    "3D_Rank": get_val(res['Ranks'], '3day', is_round=False),
                    "3D_RMSE": get_val(res['RMSE'], '3day'),
                    "3_Days_Pred(%)": get_val(res['Preds'], '3day'),
                    # 第二層: 7 天
                    "7D_Rank": get_val(res['Ranks'], '7day', is_round=False),
                    "7D_RMSE": get_val(res['RMSE'], '7day'),
                    "7_Days_Pred(%)": get_val(res['Preds'], '7day'),
                    # 第三層: 1 個月 (22交易日)
                    "1M_Rank": get_val(res['Ranks'], '1month', is_round=False),
                    "1M_RMSE": get_val(res['RMSE'], '1month'),
                    "1_Month_Pred(%)": get_val(res['Preds'], '1month'),
                    # 第四層: 1 年 (252交易日)
                    "1Y_Rank": get_val(res['Ranks'], '1year', is_round=False),
                    "1Y_RMSE": get_val(res['RMSE'], '1year'),
                    "1_Year_Pred(%)": get_val(res['Preds'], '1year'),
                    
                    "Status": "Success",
                    "Update_Time": datetime.now().strftime("%H:%M:%S")
                })
            
            df_rows = pd.DataFrame(rows_to_add)
            
            if safe_gspread_write(gc, target_sh.id, "預測紀錄", df_rows, mode="append"):
                print(f"   ✅ 成功寫入 5 層評估報告: {target_sh.title}")
                best_3d = sorted(layered_results.keys(), key=lambda m: layered_results[m]['Ranks'].get('3day', 99))[0]
                best_1y = sorted(layered_results.keys(), key=lambda m: layered_results[m]['Ranks'].get('1year', 99))[0]
                print(f"   🏆 3天短線最準: {best_3d} (RMSE: {round(layered_results[best_3d]['RMSE'].get('3day',0),2)})")
                print(f"   🏆 1年長線最準: {best_1y} (RMSE: {round(layered_results[best_1y]['RMSE'].get('1year',0),2)})")

        if first_run_pca is not None:
            df_pca_output = first_run_pca.reset_index()
            df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
            safe_gspread_write(gc, lake_sh.id, "global_pca_features", df_pca_output, mode="clear_update")
            print("\n✅ PCA 特徵已儲存回 Data Lake。")
            
        print("\n✅ 所有獨立檔案更新完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()

if __name__ == "__main__":
    main()
