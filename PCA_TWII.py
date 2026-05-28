# -*- coding: utf-8 -*-
"""
V14.6.1 PLS_TWII.py (監督式降維 PLS + 多核心平行運算 + 時光機防護版)
- 修正：修復任務清單收集邏輯，支援僅透過檔名 (file_name) 搜尋目標表格，正確觸發多核心運算。
- 演算法升級：捨棄無監督的 PCA，改採 PLS 偏最小平方法，降維時強制考慮預測目標 (y)，歐幾里得距離更精準。
- 防作弊機制：嚴格執行 Train/Test 時間切分，僅用過去資料訓練 PLS 與 XGBoost，杜絕未來數據洩漏。
- 極速並行：導入 ProcessPoolExecutor，多檔股票同時平行運算，抵銷 PLS 帶來的計算量負擔。
"""
import os
import sys
import io
import subprocess
import importlib
from datetime import datetime
import json
import time
import traceback
import re
import concurrent.futures

# 🔥 [防卡死第一道防線] 強制 Python 立即吐出所有 print 日誌
try:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

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
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet", "--user"])
            installed_any = True
    if installed_any:
        importlib.invalidate_caches()

bootstrap()

import pandas as pd
import numpy as np
from sklearn.cross_decomposition import PLSRegression # 🌟 核心：PLS 降維
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from xgboost import XGBRegressor
import gspread
from google.oauth2.service_account import Credentials

try:
    pd.set_option('future.no_silent_downcasting', True)
except Exception:
    pass

# --- 參數設定 ---
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

WINDOWS = {
    "1day": 1, 
    "3day": 3, 
    "7day": 7, 
    "1month": 21, 
    "6month": 126
}

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
            print(f"      📝 [API 進度] 準備寫入 (ID: {sp_id[:10]}...), 嘗試: {attempt+1}/3")
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                print(f"      🆕 [API 進度] 找不到分頁 '{tab_name}'，正在建立新分頁...")
                worksheet = sh.add_worksheet(title=tab_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            df = df.replace([np.inf, -np.inf], np.nan).fillna("")
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
            print(f"      ✅ [API 進度] 寫入成功！")
            return True
        except gspread.exceptions.APIError as e:
            print(f"      ⚠️ [API 警告] Google API 忙線，等待 3 秒... ({attempt+1}/3)")
            time.sleep(3)
        except Exception as e:
            print(f"      ❌ [API 致命錯誤] 寫入發生非預期錯誤:")
            traceback.print_exc()
            time.sleep(2)
    return False

def append_error_note(gc, sp_id, tab_name, error_msg):
    for attempt in range(3):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=tab_name, rows="50", cols="10")
            worksheet.append_row([error_msg])
            return True
        except Exception:
            time.sleep(2)
    return False

def load_sheet_as_dataframe(sh, worksheet_name=None):
    try:
        ws = sh.worksheet(worksheet_name) if worksheet_name else sh.get_worksheet(0)
    except Exception as e:
        raise ValueError(f"找不到分頁。錯誤: {e}")
        
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    
    if 'Date' not in df.columns:
        if '日期' in df.columns:
            df.rename(columns={'日期': 'Date'}, inplace=True)
        else:
            df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
    
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df.dropna(subset=['Date'], inplace=True)
    df.set_index('Date', inplace=True)
    
    duplicates_count = df.index.duplicated().sum()
    if duplicates_count > 0:
        print(f"      ⚠️ [資料警告] 發現 {duplicates_count} 筆重複日期，已自動清理保留最新一筆！")
        df = df[~df.index.duplicated(keep='last')]
    
    df = df.apply(pd.to_numeric, errors='coerce').ffill()
    df.dropna(axis=1, how='all', inplace=True)
    df.sort_index(inplace=True)
    return df

def find_spreadsheet(gc, file_name, file_url=""):
    for attempt in range(3):
        try:
            if file_url.strip():
                try: 
                    return gc.open_by_url(file_url.strip())
                except Exception: 
                    pass
            return gc.open(file_name)
        except gspread.exceptions.SpreadsheetNotFound:
            return None
        except gspread.exceptions.APIError:
            if attempt < 2: time.sleep(5)
        except Exception:
            if attempt < 2: time.sleep(3)
    return None

def identify_target_column(df, file_name):
    candidates = []
    if "TWII" in file_name:
        candidates = ["^twii", "twii", "加權指數", "大盤"]
    else:
        match = re.search(r'PRE_(.*?)\((.*?)\)', file_name)
        if match:
            name, ticker = match.group(1).strip(), match.group(2).strip()
            if name: candidates.append(name)
            if ticker: candidates.append(ticker)
        else:
            candidates.append(file_name.replace("PRE_", ""))
            
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and ("close" in col_lower or "收盤" in col_lower):
                return col
                
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and "volume" not in col_lower and "成交量" not in col_lower:
                return col
    return None

# ==========================================
# 🚀 核心優化：獨立平行處理單元 (Worker Function)
# ==========================================
def process_single_target(file_name, df_X_master, df_stocks, windows):
    """
    此函數為多核心運算設計，獨立處理每一檔股票的 PLS 與模型訓練。
    """
    try:
        print(f"      ⚙️ [{file_name}] 啟動 PLS 預測引擎...")
        target_col = identify_target_column(df_X_master if file_name == "PRE_TWII" else df_stocks, file_name)
        if not target_col:
            print(f"      ⚠️ [{file_name}] 找不到目標欄位。")
            return file_name, None
            
        s_y = (df_X_master if file_name == "PRE_TWII" else df_stocks)[target_col].copy()
        s_y.name = "Target_Close"
        
        # 對齊資料
        aligned_data = pd.concat([df_X_master, s_y], axis=1, join='inner').dropna()
        
        # 🚀 效能優化：過濾 5 年前的過期雜訊，只取近 3 年 (750 個交易日) 進行訓練
        aligned_data = aligned_data.tail(750)
        
        if len(aligned_data) < 100: 
            print(f"      ⚠️ [{file_name}] 有效資料不足 100 筆。")
            return file_name, None
        
        y_raw = aligned_data["Target_Close"]
        df_aligned_X = aligned_data.drop(columns=["Target_Close"]).replace([np.inf, -np.inf], 0)
        
        model_names = ['PLS_Poly_Ridge', 'RandomForest', 'XGBoost']
        model_preds, model_rmse = {m: {} for m in model_names}, {m: {} for m in model_names} 
        poly = PolynomialFeatures(degree=2, include_bias=False)
        
        for window_name, shift_days in windows.items():
            
            # 定義目標：未來的漲跌幅
            y_target = y_raw.pct_change(shift_days).shift(-shift_days) * 100
            y_target = y_target.replace([np.inf, -np.inf], np.nan)
            valid_idx = ~y_target.isna()
            
            if valid_idx.sum() < 60:
                for m in model_names: 
                    model_preds[m][window_name], model_rmse[m][window_name] = "N/A", None
                continue
                
            X_raw_v = df_aligned_X.values[valid_idx]
            Y_v = y_target[valid_idx].values
            
            # 🛡️ 時光機防護：嚴格的時間序列切分 (80% 訓練, 20% 測試)
            split_idx = int(len(Y_v) * 0.8)
            X_train_raw, X_test_raw = X_raw_v[:split_idx], X_raw_v[split_idx:]
            y_train, y_test = Y_v[:split_idx], Y_v[split_idx:]
            
            # 最新的大環境數據 (用來預測真正的未來)
            X_latest_raw = df_aligned_X.values[-1].reshape(1, -1)
            
            # 1. 獨立縮放 (避免數據洩漏，scaler 只能 fit 在 train)
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train_raw)
            X_test_scaled = scaler.transform(X_test_raw)
            X_latest_scaled = scaler.transform(X_latest_raw)
            
            # 2. 🎯 核心升級：PLS 監督式降維 🎯
            n_comp = min(10, X_train_scaled.shape[1])
            pls = PLSRegression(n_components=n_comp)
            
            X_train_pls = pls.fit_transform(X_train_scaled, y_train)[0]
            X_test_pls = pls.transform(X_test_scaled)
            X_latest_pls = pls.transform(X_latest_scaled)
            
            # 3. 建立模型 (全面改吃 PLS 量身打造出來的濃縮特徵)
            # (A) PLS_Poly_Ridge
            X_train_pls_poly = poly.fit_transform(X_train_pls)
            X_test_pls_poly = poly.transform(X_test_pls)
            X_latest_pls_poly = poly.transform(X_latest_pls)
            
            ridge = Ridge(alpha=1.0)
            ridge.fit(X_train_pls_poly, y_train)
            model_rmse['PLS_Poly_Ridge'][window_name] = float(np.sqrt(mean_squared_error(y_test, ridge.predict(X_test_pls_poly))))
            model_preds['PLS_Poly_Ridge'][window_name] = round(float(ridge.predict(X_latest_pls_poly)[0]), 2)
            
            # (B) RandomForest
            rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=1)
            rf.fit(X_train_pls, y_train)
            model_rmse['RandomForest'][window_name] = float(np.sqrt(mean_squared_error(y_test, rf.predict(X_test_pls))))
            model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_pls)[0]), 2)
            
            # (C) XGBoost
            xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror', n_jobs=1)
            xgb.fit(X_train_pls, y_train)
            model_rmse['XGBoost'][window_name] = float(np.sqrt(mean_squared_error(y_test, xgb.predict(X_test_pls))))
            model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_pls)[0]), 2)

        # 結算與排名邏輯
        layers = list(windows.keys()) + ['Overall']
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
            
        print(f"      ✅ [{file_name}] PLS 引擎運算完畢。")
        return file_name, results
        
    except Exception as e:
        print(f"      ❌ 處理 {file_name} 時發生嚴重錯誤: {str(e)}")
        traceback.print_exc()
        return file_name, None

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*70)
    print("🏆 PLS x 機器學習 (V14.6.1 監督式降維 + 多核心平行極速版)")
    print("="*70)
    
    try:
        gc = get_gspread_client()
        print("\n步驟 1: 尋找並融合三大特徵池 (總經、期貨、AI輿情)...")
        
        df_global, df_taifex, df_ai = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        sh_global = find_spreadsheet(gc, "global_market_factors")
        if sh_global: df_global = load_sheet_as_dataframe(sh_global)
        
        sh_taifex = find_spreadsheet(gc, "taifex_derivatives_history")
        if sh_taifex: df_taifex = load_sheet_as_dataframe(sh_taifex)

        sh_ai = find_spreadsheet(gc, "stock_history_AI_SCORE")
        if sh_ai: df_ai = load_sheet_as_dataframe(sh_ai)

        print("   🔄 正在將特徵池進行外部合併 (Outer Join)...")
        df_X_master = df_global.copy()
        if not df_taifex.empty:
            df_X_master = df_X_master.join(df_taifex[df_taifex.columns.difference(df_X_master.columns)], how='outer')
        if not df_ai.empty:
            df_X_master = df_X_master.join(df_ai[df_ai.columns.difference(df_X_master.columns)], how='outer')

        df_X_master = df_X_master.sort_index().ffill().fillna(0).replace([np.inf, -np.inf], 0)
        print(f"   🔥 終極特徵矩陣融合完畢！總天數: {len(df_X_master)}")

        print("\n步驟 2: 載入個股歷史資料 (stock_history_13_targets)...")
        stock_sh = find_spreadsheet(gc, "stock_history_13_targets")
        if not stock_sh: raise ValueError("找不到個股目標檔案")
        df_stocks = load_sheet_as_dataframe(stock_sh)

        print(f"\n🎯 步驟 3: 啟動 PLS 多核心平行運算引擎...")
        today_str, today_dot = datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y.%m.%d")
        
        # 🚀 修正：將 TARGET_SPREADSHEETS 所有的 key (檔名) 列入任務清單，無視 file_url 空字串
        tasks = list(TARGET_SPREADSHEETS.keys())
        print(f"   📋 共獲取 {len(tasks)} 檔標的排隊進入引擎。")
                
        results_map = {}
        
        # 啟動多核心運算 (ProcessPoolExecutor)
        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = []
            for file_name in tasks:
                futures.append(executor.submit(process_single_target, file_name, df_X_master, df_stocks, WINDOWS))
                
            # 收集結果
            for future in concurrent.futures.as_completed(futures):
                f_name, res = future.result()
                if res:
                    results_map[f_name] = res
                    
        # 📝 步驟 4: 統一寫回 Google Sheets，避免 API 連線衝突
        print("\n步驟 4: 正在統整分析結果，準備同步至雲端...")
        header_order = [
            "Date", "Model_Name", 
            "Overall_Rank", "Overall_RMSE",
            "1D_Rank", "1D_RMSE", "1_Day_Pred(%)",
            "3D_Rank", "3D_RMSE", "3_Days_Pred(%)",
            "7D_Rank", "7D_RMSE", "7_Days_Pred(%)",
            "1M_Rank", "1M_RMSE", "1_Month_Pred(%)",
            "6M_Rank", "6M_RMSE", "6_Months_Pred(%)",
            "Status", "Update_Time"
        ]
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            if file_name not in results_map:
                print(f"   ⏭️ [{file_name}] 無預測結果，跳過。")
                continue
                
            print(f"\n👉 尋找並準備寫入: 【{file_name}】")
            dest_sh = find_spreadsheet(gc, file_name, file_url)
            if not dest_sh:
                print(f"   ❌ 雲端找不到檔案 '{file_name}'，寫入失敗。")
                continue
                
            result = results_map[file_name]
            rows_to_add = []
            
            for m in sorted(result.keys(), key=lambda x: result[x]['Ranks'].get('Overall', 99)):
                res = result[m]
                def get_val(d, k, is_round=True):
                    v = d.get(k)
                    return "N/A" if v is None or pd.isna(v) else (round(float(v), 2) if is_round else v)
                
                rows_to_add.append({
                    "Date": today_str, "Model_Name": m,
                    "Overall_Rank": get_val(res['Ranks'], 'Overall', False), "Overall_RMSE": get_val(res['RMSE'], 'Overall'),
                    "1D_Rank": get_val(res['Ranks'], '1day', False), "1D_RMSE": get_val(res['RMSE'], '1day'), "1_Day_Pred(%)": get_val(res['Preds'], '1day'),
                    "3D_Rank": get_val(res['Ranks'], '3day', False), "3D_RMSE": get_val(res['RMSE'], '3day'), "3_Days_Pred(%)": get_val(res['Preds'], '3day'),
                    "7D_Rank": get_val(res['Ranks'], '7day', False), "7D_RMSE": get_val(res['RMSE'], '7day'), "7_Days_Pred(%)": get_val(res['Preds'], '7day'),
                    "1M_Rank": get_val(res['Ranks'], '1month', False), "1M_RMSE": get_val(res['RMSE'], '1month'), "1_Month_Pred(%)": get_val(res['Preds'], '1month'),
                    "6M_Rank": get_val(res['Ranks'], '6month', False), "6M_RMSE": get_val(res['RMSE'], '6month'), "6_Months_Pred(%)": get_val(res['Preds'], '6month'),
                    "Status": "Success", "Update_Time": datetime.now().strftime("%H:%M:%S")
                })
            
            df_output = pd.DataFrame(rows_to_add)[header_order]
            safe_gspread_write(gc, dest_sh.id, "預測紀錄", df_output, mode="clear_update")
            
        print("\n✅ 所有流程完畢！V14.6.1 系統已登出。")
        
    except Exception as e:
        print(f"\n❌ 重大錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
