# -*- coding: utf-8 -*-
"""
13檔預測標的爬蟲微服務 (Target_Stocks_Data_Lake.py)
專門負責向 Yahoo Finance 請求 13 檔個股的 5 年歷史股價與成交量，
並寫入專屬的 Google Sheet 中，供中央大腦作為預測目標 (y) 使用。
"""
import os
import json
import pandas as pd
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "stock_history_13_targets"  # 獨立的 13 檔標的資料湖
PERIOD = "5y"  # 初始抓取五年資料

# 預設要抓取的 13 檔預測標的 (對應大腦預期的欄位)
TARGET_TICKERS = [
    "2330.TW",  # 台積電
    "2303.TW",  # 聯電
    "2356.TW",  # 英業達
    "2002.TW",  # 中鋼
    "NVDA",     # NVIDIA
    "TSLA",     # TESLA
    "INTC",     # INTEL
    "AAPL",     # Apple
    "MSFT",     # Microsoft
    "AMZN",     # Amazon
    "LLY",      # Eli Lilly
    "NVO",      # Novo Nordisk
    "7203.T"    # Toyota
]

def extract_series_safely(df, ticker, is_multi):
    """安全地從 Yahoo 批次下載的 DataFrame 中提取單一指標的收盤價與成交量"""
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    
    try:
        # yfinance 新版回傳 MultiIndex，利用 KeyError 捕捉取代 in 判斷更安全
        if is_multi:
            close_s = df['Close'][ticker]
            vol_s = df['Volume'][ticker]
        else:
            close_s = df['Close']
            vol_s = df['Volume']
        return close_s, vol_s
    except KeyError:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float), pd.Series(dtype=float)

def main():
    print("===========================================")
    print(f"🎯 啟動【13檔預測標的】無污染純淨數據任務 (期間: {PERIOD})")
    print("===========================================")

    # ------------------------------------------------
    # 1. 批次下載五年歷史資料
    # ------------------------------------------------
    print(f"🕸️ 階段一：向 Yahoo 請求 {len(TARGET_TICKERS)} 檔指標近 {PERIOD} 的歷史數據...")
    df_bulk = yf.download(TARGET_TICKERS, period=PERIOD, threads=True, progress=False)
    is_multi = len(TARGET_TICKERS) > 1

    # ------------------------------------------------
    # 2. 建立主資料表 (DataFrame) 並合併所有資料
    # ------------------------------------------------
    print("🧠 階段二：資料合併與日曆對齊中...")
    merged_df = pd.DataFrame(index=df_bulk.index)
    
    for ticker in TARGET_TICKERS:
        close_series, vol_series = extract_series_safely(df_bulk, ticker, is_multi)
        # 欄位命名規則：Ticker_Close (這正是 PCA 大腦需要的名稱)
        merged_df[f"{ticker}_Close"] = close_series
        merged_df[f"{ticker}_Volume"] = vol_series

    # ------------------------------------------------
    # 3. 處理空值與格式轉換 (保留真實市場狀態)
    # ------------------------------------------------
    print("✨ 階段三：格式化數據 (保留真實空值，不強行補零)...")
    
    close_cols = [c for c in merged_df.columns if c.endswith("_Close")]
    vol_cols = [c for c in merged_df.columns if c.endswith("_Volume")]

    # 收盤價：不補值，僅做四捨五入到小數點後 4 位
    merged_df[close_cols] = merged_df[close_cols].round(4)

    # ------------------------------------------------
    # 4. 轉換為 Google Sheet 寫入格式
    # ------------------------------------------------
    print("📋 階段四：轉換為 Google Sheet 寫入格式...")
    
    # 關鍵修復：強制將索引命名為 'Date'
    merged_df.index.name = 'Date'
    merged_df = merged_df.reset_index()
    
    # 統一將 Date 轉為 YYYY-MM-DD 並去除時區，以利後續合併
    merged_df['Date'] = pd.to_datetime(merged_df['Date']).dt.tz_localize(None).dt.strftime('%Y-%m-%d')
    
    # 交易量防呆處理：有數值的轉整數(去掉.0)，沒有數值的(NaN)轉為空字串 ""
    for col in vol_cols:
        merged_df[col] = merged_df[col].apply(lambda x: int(x) if pd.notnull(x) else "")

    # 收盤價防呆處理：將剩下的任何 NaN 轉為空字串，以符合 Google Sheet 空白儲存格的邏輯
    merged_df = merged_df.fillna("")

    # 轉換成 List of Lists 以便寫入 Google Sheet
    output_data = [merged_df.columns.tolist()] + merged_df.values.tolist()

    # ------------------------------------------------
    # 5. 連線 Google Sheet 並強制覆蓋寫入
    # ------------------------------------------------
    print("☁️ 階段五：連線 Google Sheet 並寫入資料...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
    
    if not creds_json:
        print("❌ 找不到 GSPREAD_CREDENTIALS 環境變數。")
        return
        
    credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(credentials)
    
    try:
        sh = gc.open(SHEET_NAME)
        wks = sh.sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ 找不到檔案 [{SHEET_NAME}]！請先在 Google Drive 手動建立一個名為 '{SHEET_NAME}' 的空白試算表。")
        return
    except Exception as e:
        print(f"❌ 讀取失敗，錯誤: {e}")
        return

    try:
        print("   正在清空舊表並寫入全新的巨量資料...")
        wks.clear()
        wks.update("A1", output_data) 
        print(f"   🎉 任務完成！共寫入 {len(output_data)} 列高純度市場資料！")
    except Exception as e:
        print(f"❌ 寫回 Google Sheet 失敗: {e}")

if __name__ == "__main__":
    main()
