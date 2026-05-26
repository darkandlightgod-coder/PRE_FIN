# -*- coding: utf-8 -*-
"""
V11.0 PCA_TWII.py (跨國全自動對齊版)
整合 13 檔個股預測與非線性多項式展開 (PolynomialFeatures)
內建 .ffill() 處理跨國休市空值，並自動解析 Ticker 抓取真實目標 (Y)。
"""
import os
import sys
import json
import time
import traceback
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# 設定字體，避免圖表中文亂碼
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# 目標預測清單
TARGET_SHEETS = [
    "PRE_台積電(2330)", "PRE_聯電(2303)", "PRE_英業達(2356)", "PRE_中鋼(2002)",
    "PRE_NVIDIA(NVDA)", "PRE_TESLA(TSLA)", "PRE_INTEL(INTC)", "PRE_Apple(AAPL)",
    "PRE_Microsoft(MSFT)", "PRE_Amazon(AMZN)", "PRE_Eli Lilly(LLY)", "PRE_Novo Nordisk(NVO)",
    "PRE_Toyota(7203)"
]

# 預測時間窗格 (交易日)
WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

# ==========================================
# Google Sheets 連線與工具函數
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        # 本地端測試：請確保 credentials.json 存在
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(creds)

def safe_gspread_write(gc, sp_id, sheet_name, df, mode="clear_update"):
    """安全寫入 Google Sheets，具備重試機制以避免 API 限制"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(sheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=sheet_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            # 將 DataFrame 轉為可寫入的二維陣列 (處理 NaN)
            df = df.fillna("")
            data = [df.columns.values.tolist()] + df.values.tolist()
            
            if mode == "clear_update":
                worksheet.clear()
                worksheet.update(values=data, range_name=None)
            elif mode == "append":
                worksheet.append_rows(df.values.tolist())
                
            print(f"✅ 成功寫入工作表: {sheet_name} (Mode: {mode})")
            return True
        except Exception as e:
            print(f"⚠️ 寫入 {sheet_name} 失敗 (嘗試 {attempt+1}/{max_retries}): {e}")
            time.sleep(3)
    return False

def load_data_lake(gc, sp_id):
    """讀取 global_market_factors 作為特徵池 (X)"""
    sh = gc.open_by_key(sp_id)
    ws = sh.worksheet("global_market_factors")
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    
    # 將所有資料轉為數值，無法轉換的變成 NaN
    df = df.apply(pd.to_numeric, errors='coerce')
    
    # 🌟 核心：使用 forward fill 填補跨國休市產生的空洞！
    df = df.ffill().bfill()
    return df

# ==========================================
# 股票代碼解析與獲取函數
# ==========================================
def extract_ticker(sheet_name):
    """從工作表名稱萃取 Yahoo Finance 的 Ticker"""
    match = re.search(r'\((.*?)\)', sheet_name)
    if not match:
        return None
    
    ticker_core = match.group(1)
    
    if ticker_core.isdigit():
        if len(ticker_core) == 4:
            return f"{ticker_core}.TW" # 台股
        elif ticker_core == "7203":
            return "7203.T" # 豐田 (日股)
    
    return ticker_core # 美股 (NVDA, TSLA 等)

# ==========================================
# 機器學習訓練與預測核心
# ==========================================
def predict_stock_returns(X_pca_df, ticker):
    """為單一股票訓練模型並產生預測"""
    # 1. 抓取該股票歷史真實價格作為目標 (Y)
    print(f"   📥 正在抓取 {ticker} 歷史價格作為訓練目標...")
    start_date = X_pca_df.index.min().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    stock_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
    
    if stock_data.empty:
        print(f"   ❌ 找不到 {ticker} 的歷史資料。")
        return None
    
    # 整理 Y 並與 X 對齊日期
    y_raw = stock_data['Close']
    if isinstance(y_raw, pd.DataFrame):
        y_raw = y_raw.iloc[:, 0] # 處理 MultiIndex 狀況
        
    y_raw.index = pd.to_datetime(y_raw.index)
    # 將 X (PCA特徵) 與 Y (股價) 用 index (日期) 對齊，捨棄兩邊配不上的日子
    aligned_data = pd.concat([X_pca_df, y_raw.rename("Close")], axis=1).dropna()
    
    if aligned_data.empty:
        return None

    X_aligned = aligned_data.drop(columns=["Close"]).values
    prices = aligned_data["Close"].values
    
    predictions = {}
    
    # 2. 針對不同時間窗格進行預測
    for window_name, shift_days in WINDOWS.items():
        # 計算未來 N 天的報酬率作為 Y (例如：把 3 天後的報酬率，放在今天的列)
        # pct_change(N).shift(-N) 確保我們是用 "今天的特徵" 預測 "未來的回報"
        y_target = aligned_data["Close"].pct_change(shift_days).shift(-shift_days) * 100
        
        # 移除最後 N 天 (因為它們沒有未來 N 天的答案，無法當作訓練資料)
        valid_idx = ~y_target.isna()
        X_train = X_aligned[valid_idx]
        Y_train = y_target[valid_idx].values
        
        if len(X_train) < 50: # 資料太少不具代表性
            predictions[window_name] = "N/A"
            continue
            
        # 多項式特徵展開 (捕捉非線性關聯，例如: 股市過熱時反而會跌)
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_poly = poly.fit_transform(X_train)
        
        # 建立 Ridge 迴歸模型並訓練 (L2正則化防止過度擬合)
        model = Ridge(alpha=1.0)
        model.fit(X_train_poly, Y_train)
        
        # 使用「最後一天的最新特徵」預測未來
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
    print("🧠 PCA 降維與 Ridge 多維預測大腦 (13檔跨國對齊版)")
    print(f"啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        # 假設你的資料都在第一個試算表中，若有多個請用 open("你的試算表名稱")
        sp_id = gc.list_spreadsheet_files()[0]['id'] 
        
        print("\n步驟 1: 載入並清理資料湖 (Data Lake)...")
        df_lake = load_data_lake(gc, sp_id)
        print(f"成功載入特徵，資料筆數: {len(df_lake)}")
        
        print("\n步驟 2: 執行全局 PCA 降維萃取大盤核心情緒...")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(df_lake)
        
        pca = PCA(n_components=5)
        feats = pca.fit_transform(X_scaled)
        
        df_pca = pd.DataFrame(feats, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)])
        # 記錄主成分解釋的變異比例
        variance_ratio = pca.explained_variance_ratio_
        print(f"前五大主成分累積解釋力: {sum(variance_ratio)*100:.2f}%")
        
        # 將 PCA 特徵寫回 Google Sheets
        df_pca_output = df_pca.reset_index()
        df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
        safe_gspread_write(gc, sp_id, "global_pca_features", df_pca_output, mode="clear_update")

        print(f"\n🎯 步驟 3: 啟動 13 檔權值股 Polynomial 預測程序...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for sheet_name in TARGET_SHEETS:
            print(f"\n👉 處理標的: {sheet_name}")
            ticker = extract_ticker(sheet_name)
            
            if not ticker:
                print(f"   ⚠️ 無法解析 Ticker，跳過。")
                continue
                
            # 進行預測
            preds = predict_stock_returns(df_pca, ticker)
            
            if preds:
                # 準備寫入格式
                row_data = pd.DataFrame([{
                    "Date": today_str,
                    "3_Days_Pred(%)": preds.get("3day", "N/A"),
                    "7_Days_Pred(%)": preds.get("7day", "N/A"),
                    "1_Month_Pred(%)": preds.get("1month", "N/A"),
                    "1_Year_Pred(%)": preds.get("1year", "N/A"),
                    "Status": "Success",
                    "Update_Time": datetime.now().strftime("%H:%M:%S")
                }])
                
                # 追加到該股票專屬的預測表中 (Append mode)
                safe_gspread_write(gc, sp_id, sheet_name, row_data, mode="append")
                print(f"   📊 預測結果: 3天[{preds.get('3day')}%], 7天[{preds.get('7day')}%], 1月[{preds.get('1month')}%]")
            else:
                print(f"   ⚠️ {sheet_name} 預測失敗，跳過。")

        print("\n✅ 所有 13 檔標的預測與寫入已完成！")
        
    except Exception as e:
        print(f"\n❌ 執行發生致命錯誤:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
