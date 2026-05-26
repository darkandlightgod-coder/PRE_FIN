# -*- coding: utf-8 -*-
"""
V11.5 PCA_TWII.py (含大盤預測版)
新增台灣加權指數 (PRE_TWII) 預測，並維持 14 個獨立檔案寫入架構。
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
    "PRE_TWII": "",         # 🆕 新增：台灣加權指數大盤
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
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動環境檢查...")
    dependencies = {
        "pandas": "pandas",
        "numpy": "numpy",
        "sklearn": "scikit-learn",
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

def safe_gspread_write(gc, sp_id, tab_name, df, mode="clear_update"):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=tab_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            df = df.fillna("")
            data = [df.columns.values.tolist()] + df.values.tolist()
            
            if mode == "clear_update":
                worksheet.clear()
                worksheet.update(values=data, range_name=None)
            elif mode == "append":
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
    
    if df.empty:
        raise ValueError("資料清洗後變成完全空值！")
        
    return df

def find_independent_spreadsheet(gc, file_name, file_url):
    if file_url.strip():
        try:
            return gc.open_by_url(file_url.strip())
        except Exception:
            return None
            
    files = gc.list_spreadsheet_files()
    for f in files:
        if f.get('name') == file_name:
            return gc.open_by_key(f['id'])
    return None

# ==========================================
# 股票代碼與預測核心
# ==========================================
def extract_ticker(file_name):
    if file_name == "PRE_TWII": return "^TWII"  # 🆕 台灣加權指數的 Yahoo Finance 代碼
    match = re.search(r'\((.*?)\)', file_name)
    if not match: return None
    t = match.group(1)
    if t.isdigit() and len(t) == 4: return f"{t}.TW"
    if t == "7203": return "7203.T"
    return t

def predict_stock_returns(X_pca_df, ticker):
    start_date = X_pca_df.index.min().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    stock_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
    
    if stock_data.empty: return None
    
    y_raw = stock_data['Close']
    if isinstance(y_raw, pd.DataFrame): y_raw = y_raw.iloc[:, 0]
        
    y_raw.index = pd.to_datetime(y_raw.index)
    aligned_data = pd.concat([X_pca_df, y_raw.rename("Close")], axis=1).dropna()
    
    if aligned_data.empty: return None

    X_aligned = aligned_data.drop(columns=["Close"]).values
    
    predictions = {}
    for window_name, shift_days in WINDOWS.items():
        # 預測目標：未來 N 天的「報酬率」 (百分比)
        y_target = aligned_data["Close"].pct_change(shift_days).shift(-shift_days) * 100
        valid_idx = ~y_target.isna()
        X_train = X_aligned[valid_idx]
        Y_train = y_target[valid_idx].values
        
        if len(X_train) < 30: 
            predictions[window_name] = "N/A"
            continue
            
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_poly = poly.fit_transform(X_train)
        
        model = Ridge(alpha=1.0)
        model.fit(X_train_poly, Y_train)
        
        X_latest = X_aligned[-1].reshape(1, -1)
        X_latest_poly = poly.transform(X_latest)
        pred_value = model.predict(X_latest_poly)[0]
        
        predictions[window_name] = round(pred_value, 2)
        
    return predictions

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*60)
    print("🧠 PCA 預測大腦 (含大盤預測版)")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        lake_sh = None
        
        print("\n步驟 1: 尋找 Data Lake 試算表...")
        if DATA_LAKE_URL.strip():
            lake_sh = gc.open_by_url(DATA_LAKE_URL.strip())
        else:
            for f in gc.list_spreadsheet_files():
                try:
                    temp_sh = gc.open_by_key(f['id'])
                    temp_sh.worksheet("global_market_factors")
                    lake_sh = temp_sh
                    print(f"   🎯 找到 Data Lake: {lake_sh.title}")
                    break
                except Exception:
                    continue
                    
        if not lake_sh:
            raise ValueError("找不到包含 'global_market_factors' 的資料湖！")
            
        print("\n步驟 2: 載入並清理 Data Lake...")
        df_lake = load_data_lake(lake_sh)
        print(f"   ✅ 成功載入特徵，資料筆數: {len(df_lake)}")
        
        print("\n步驟 3: 執行 PCA 降維並寫回 Data Lake...")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(df_lake)
        
        pca = PCA(n_components=5)
        feats = pca.fit_transform(X_scaled)
        
        df_pca = pd.DataFrame(feats, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)])
        df_pca_output = df_pca.reset_index()
        df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
        safe_gspread_write(gc, lake_sh.id, "global_pca_features", df_pca_output, mode="clear_update")
        print("   ✅ PCA 特徵已儲存回 Data Lake。")

        print(f"\n🎯 步驟 4: 啟動跨檔案預測寫入程序...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉 處理標的: {file_name}")
            
            target_sh = find_independent_spreadsheet(gc, file_name, file_url)
            if not target_sh:
                print(f"   ❌ 找不到名為 '{file_name}' 的獨立試算表。")
                continue
                
            ticker = extract_ticker(file_name)
            if not ticker: continue
            preds = predict_stock_returns(df_pca, ticker)
            
            if preds:
                row_data = pd.DataFrame([{
                    "Date": today_str,
                    "3_Days_Pred(%)": preds.get("3day", "N/A"),
                    "7_Days_Pred(%)": preds.get("7day", "N/A"),
                    "1_Month_Pred(%)": preds.get("1month", "N/A"),
                    "1_Year_Pred(%)": preds.get("1year", "N/A"),
                    "Status": "Success",
                    "Update_Time": datetime.now().strftime("%H:%M:%S")
                }])
                
                if safe_gspread_write(gc, target_sh.id, "預測紀錄", row_data, mode="append"):
                    print(f"   ✅ 成功寫入獨立檔案 -> {target_sh.title} (分頁: 預測紀錄)")
                    print(f"   📊 預測結果: 3天[{preds.get('3day')}%], 1月[{preds.get('1month')}%]")
            else:
                print(f"   ⚠️ {file_name} 預測失敗或無足夠股票資料。")

        print("\n✅ 所有獨立檔案更新完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()

if __name__ == "__main__":
    main()
