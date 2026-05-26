# -*- coding: utf-8 -*-
"""
V11.2 PCA_TWII.py (增強除錯與防呆版)
加強 Google Sheets 讀取防呆機制、Date 欄位自動偵測
"""
import os
import sys
import subprocess
import importlib
from datetime import datetime

# ==========================================
# 【0. 環境自癒與延遲載入】
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

TARGET_SHEETS = [
    "PRE_台積電(2330)", "PRE_聯電(2303)", "PRE_英業達(2356)", "PRE_中鋼(2002)",
    "PRE_NVIDIA(NVDA)", "PRE_TESLA(TSLA)", "PRE_INTEL(INTC)", "PRE_Apple(AAPL)",
    "PRE_Microsoft(MSFT)", "PRE_Amazon(AMZN)", "PRE_Eli Lilly(LLY)", "PRE_Novo Nordisk(NVO)",
    "PRE_Toyota(7203)"
]

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

def safe_gspread_write(gc, sp_id, sheet_name, df, mode="clear_update"):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(sheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=sheet_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            df = df.fillna("")
            data = [df.columns.values.tolist()] + df.values.tolist()
            
            if mode == "clear_update":
                worksheet.clear()
                worksheet.update(values=data, range_name=None)
            elif mode == "append":
                worksheet.append_rows(df.values.tolist())
                
            print(f"   ✅ 成功寫入: {sheet_name}")
            return True
        except Exception as e:
            print(f"   ⚠️ 寫入失敗 (嘗試 {attempt+1}): {e}")
            time.sleep(2)
    return False

def load_data_lake(gc, sp_id):
    """讀取並強化清理資料湖 (具備防呆機制)"""
    sh = gc.open_by_key(sp_id)
    print(f"   📄 成功連線試算表: {sh.title}")
    
    try:
        ws = sh.worksheet("global_market_factors")
    except gspread.exceptions.WorksheetNotFound:
        raise ValueError(f"找不到分頁 'global_market_factors'！請確認爬蟲是否有寫入此檔案 ({sh.title})。")
        
    data = ws.get_all_values()
    if not data or len(data) < 2:
        raise ValueError("分頁 'global_market_factors' 沒有資料或只有標題！無法進行 PCA 分析。")
        
    df = pd.DataFrame(data[1:], columns=data[0])
    
    # 防呆：如果找不到 Date，試著找找看有沒有中文的「日期」，或者強制拿第一欄
    if 'Date' not in df.columns:
        if '日期' in df.columns:
            df.rename(columns={'日期': 'Date'}, inplace=True)
            print("   ⚠️ 發現欄位名稱為 '日期'，已自動轉換為 'Date'")
        else:
            first_col = df.columns[0]
            df.rename(columns={first_col: 'Date'}, inplace=True)
            print(f"   ⚠️ 找不到 Date 欄位，強制將第一欄 '{first_col}' 視為 Date")
    
    try:
        df['Date'] = pd.to_datetime(df['Date'])
    except Exception as e:
        raise ValueError(f"日期格式轉換失敗！請檢查 Date 欄位裡是不是有奇怪的文字。詳細錯誤: {e}")
        
    df.set_index('Date', inplace=True)
    df = df.apply(pd.to_numeric, errors='coerce')
    df = df.ffill().bfill() # 填補各國休市空值
    
    # 刪除完全是空值的欄位
    df.dropna(axis=1, how='all', inplace=True)
    
    if df.empty:
        raise ValueError("資料清洗後變成完全空值！請檢查表內資料是否都是非數字的字串。")
        
    return df

# ==========================================
# 股票代碼與預測核心
# ==========================================
def extract_ticker(sheet_name):
    match = re.search(r'\((.*?)\)', sheet_name)
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
    print("🧠 PCA 預測大腦 (防呆診斷版)")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        files = gc.list_spreadsheet_files()
        if not files:
            raise ValueError("您的服務帳戶沒有存取任何試算表的權限！請確認您有將試算表共用給服務帳戶的 Email。")
            
        sp_id = files[0]['id'] 
        
        print("\n步驟 1: 載入並清理資料湖 (Data Lake)...")
        df_lake = load_data_lake(gc, sp_id)
        print(f"   ✅ 成功載入特徵，資料筆數: {len(df_lake)}")
        
        print("\n步驟 2: 執行全局 PCA 降維萃取大盤核心情緒...")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(df_lake)
        
        pca = PCA(n_components=5)
        feats = pca.fit_transform(X_scaled)
        
        df_pca = pd.DataFrame(feats, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)])
        df_pca_output = df_pca.reset_index()
        df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
        safe_gspread_write(gc, sp_id, "global_pca_features", df_pca_output, mode="clear_update")

        print(f"\n🎯 步驟 3: 啟動預測程序...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for sheet_name in TARGET_SHEETS:
            print(f"\n👉 處理標的: {sheet_name}")
            ticker = extract_ticker(sheet_name)
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
                safe_gspread_write(gc, sp_id, sheet_name, row_data, mode="append")
                print(f"   📊 預測結果: 3天[{preds.get('3day')}%], 1月[{preds.get('1month')}%]")
            else:
                print(f"   ⚠️ {sheet_name} 預測失敗或無足夠資料。")

        print("\n✅ 流程執行完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生錯誤 (白話文診斷):")
        print(f"⚠️ {str(e)}\n")
        print("🔍 原始錯誤 Traceback 如下 (供工程師參考):")
        traceback.print_exc()

if __name__ == "__main__":
    main()
