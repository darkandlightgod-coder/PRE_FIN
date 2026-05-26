# -*- coding: utf-8 -*-
"""
V12.2 PCA_TWII.py (多模型競技版 Model Arena - 智慧標題覆蓋)
同時執行 PCA+Ridge、RandomForest、XGBoost，評估準確度(RMSE)並進行排名。
自動偵測舊版格式並覆蓋，確保擁有正確的欄位名稱。
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
    "PRE_Toyota(7203)": ""
}

# ==========================================
# 【環境自癒與延遲載入】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動環境檢查 (包含進階機器學習套件)...")
    dependencies = {
        "pandas": "pandas",
        "numpy": "numpy",
        "sklearn": "scikit-learn",
        "xgboost": "xgboost",           
        "gspread": "gspread",
        "google.oauth2.service_account": "google-auth",
        "yfinance": "yfinance"
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
import yfinance as yf

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
                # 建立新分頁
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
                    # 分頁全空，先寫入標題
                    worksheet.append_row(new_headers)
                elif existing_data[0] != new_headers:
                    # 💡 智慧偵測：如果舊的標題跟新標題不一樣，代表是舊格式，直接清空並寫入新標題
                    print("     🧹 偵測到舊版格式，清空並覆寫新標題...")
                    worksheet.clear()
                    worksheet.append_row(new_headers)
                
                # 接著寫入今天的多模型預測資料
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

def extract_ticker(file_name):
    if file_name == "PRE_TWII": return "^TWII"
    match = re.search(r'\((.*?)\)', file_name)
    if not match: return None
    t = match.group(1)
    if t.isdigit() and len(t) == 4: return f"{t}.TW"
    if t == "7203": return "7203.T"
    return t

# ==========================================
# 🚀 核心：多模型競技與評估 (Model Arena)
# ==========================================
def predict_with_arena(df_lake, ticker):
    scaler = StandardScaler()
    X_scaled_np = scaler.fit_transform(df_lake)
    df_X_scaled = pd.DataFrame(X_scaled_np, index=df_lake.index, columns=df_lake.columns)
    
    pca = PCA(n_components=5)
    X_pca_np = pca.fit_transform(X_scaled_np)
    df_X_pca = pd.DataFrame(X_pca_np, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)])
    
    start_date = df_lake.index.min().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    stock_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
    
    if stock_data.empty: return None
    
    y_raw = stock_data['Close']
    if isinstance(y_raw, pd.DataFrame): y_raw = y_raw.iloc[:, 0]
    y_raw.index = pd.to_datetime(y_raw.index)
    
    aligned_data = pd.concat([df_X_scaled, df_X_pca, y_raw.rename("Close")], axis=1).dropna()
    if aligned_data.empty: return None

    model_names = ['PCA_Poly_Ridge', 'RandomForest', 'XGBoost']
    model_preds = {m: {} for m in model_names}
    model_errors = {m: [] for m in model_names} 
    
    for window_name, shift_days in WINDOWS.items():
        y_target = aligned_data["Close"].pct_change(shift_days).shift(-shift_days) * 100
        valid_idx = ~y_target.isna()
        
        if valid_idx.sum() < 60:
            for m in model_names: model_preds[m][window_name] = "N/A"
            continue
            
        X_raw_v = aligned_data[df_lake.columns].values[valid_idx]
        X_pca_v = aligned_data[[f"PC{i+1}" for i in range(5)]].values[valid_idx]
        Y_v = y_target[valid_idx].values
        
        split_idx = int(len(Y_v) * 0.8)
        
        X_latest_raw = aligned_data[df_lake.columns].values[-1].reshape(1, -1)
        X_latest_pca = aligned_data[[f"PC{i+1}" for i in range(5)]].values[-1].reshape(1, -1)
        
        # --- 模型 1: PCA + Polynomial + Ridge ---
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_pca_poly = poly.fit_transform(X_pca_v[:split_idx])
        X_test_pca_poly = poly.transform(X_pca_v[split_idx:])
        
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train_pca_poly, Y_v[:split_idx])
        r_preds_test = ridge.predict(X_test_pca_poly)
        r_rmse = float(np.sqrt(mean_squared_error(Y_v[split_idx:], r_preds_test)))
        
        model_errors['PCA_Poly_Ridge'].append(r_rmse)
        model_preds['PCA_Poly_Ridge'][window_name] = round(float(ridge.predict(poly.transform(X_latest_pca))[0]), 2)
        
        # --- 模型 2: Random Forest ---
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        rf_preds_test = rf.predict(X_raw_v[split_idx:])
        rf_rmse = float(np.sqrt(mean_squared_error(Y_v[split_idx:], rf_preds_test)))
        
        model_errors['RandomForest'].append(rf_rmse)
        model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_raw)[0]), 2)
        
        # --- 模型 3: XGBoost ---
        xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror')
        xgb.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        xgb_preds_test = xgb.predict(X_raw_v[split_idx:])
        xgb_rmse = float(np.sqrt(mean_squared_error(Y_v[split_idx:], xgb_preds_test)))
        
        model_errors['XGBoost'].append(xgb_rmse)
        model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_raw)[0]), 2)

    rankings = []
    for m in model_names:
        avg_rmse = float(np.mean(model_errors[m])) if model_errors[m] else 9999.99
        rankings.append({
            'Model_Name': m,
            'Eval_Error(RMSE)': round(avg_rmse, 2),
            'Preds': model_preds[m]
        })
        
    rankings.sort(key=lambda x: x['Eval_Error(RMSE)'])
    
    for i, r in enumerate(rankings):
        r['Rank'] = i + 1
        
    return rankings, df_X_pca

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*60)
    print("🏆 PCA x 機器學習 預測大腦 (多模型競技版)")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        lake_sh = None
        
        print("\n步驟 1: 載入 Data Lake...")
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
        print(f"   ✅ 成功載入特徵，資料筆數: {len(df_lake)}")
        
        print(f"\n🎯 步驟 2: 啟動多模型預測與跨檔案寫入...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        first_run_pca = None
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉 處理標的: {file_name}")
            
            target_sh = find_independent_spreadsheet(gc, file_name, file_url)
            if not target_sh:
                print(f"   ❌ 找不到檔案。")
                continue
                
            ticker = extract_ticker(file_name)
            if not ticker: continue
            
            result = predict_with_arena(df_lake, ticker)
            if not result:
                print(f"   ⚠️ 資料不足，跳過。")
                continue
                
            rankings, df_pca_features = result
            if first_run_pca is None: first_run_pca = df_pca_features
            
            rows_to_add = []
            for r in rankings:
                rows_to_add.append({
                    "Date": today_str,
                    "Rank": r['Rank'],
                    "Model_Name": r['Model_Name'],
                    "Eval_Error(RMSE)": r['Eval_Error(RMSE)'],
                    "3_Days_Pred(%)": r['Preds'].get("3day", "N/A"),
                    "7_Days_Pred(%)": r['Preds'].get("7day", "N/A"),
                    "1_Month_Pred(%)": r['Preds'].get("1month", "N/A"),
                    "1_Year_Pred(%)": r['Preds'].get("1year", "N/A"),
                    "Status": "Success",
                    "Update_Time": datetime.now().strftime("%H:%M:%S")
                })
            
            df_rows = pd.DataFrame(rows_to_add)
            
            # 使用 append 模式，裡面會智慧判斷需不需要清空舊版標題
            if safe_gspread_write(gc, target_sh.id, "預測紀錄", df_rows, mode="append"):
                best_model = rankings[0]['Model_Name']
                print(f"   ✅ 成功寫入: {target_sh.title} (分頁: 預測紀錄)")
                print(f"   🏆 最準確模型: {best_model} (誤差: {rankings[0]['Eval_Error(RMSE)']})")

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
