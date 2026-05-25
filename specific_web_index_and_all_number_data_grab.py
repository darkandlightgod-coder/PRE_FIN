# -*- coding: utf-8 -*-
import os
import json
import time
import pandas as pd
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
PERIOD = "1mo"  # 若要補 5 年，請改成 "5y" 執行一次即可
DELAY_SECONDS = 1.5  # 每次請求間隔 1.5 秒，防止被 Yahoo 封鎖

def get_tickers_from_headers(headers):
    """掃描表頭，自動提取所有股票代號"""
    tickers = set()
    for header in headers:
        if header.endswith("_Close") or header.endswith("_Volume"):
            ticker = header.split('_')[0]
            tickers.add(ticker)
    return sorted(list(tickers))

def fetch_stock_data(ticker, period):
    """
    智能下載器：先嘗試 .TW (上市)，若失敗自動嘗試 .TWO (上櫃)
    """
    suffixes = [".TW", ".TWO"]
    
    for suffix in suffixes:
        symbol = f"{ticker}{suffix}"
        try:
            hist = yf.Ticker(symbol).history(period=period)
            if not hist.empty:
                print(f"      ✅ 成功取得 {symbol} 資料 ({len(hist)} 筆)")
                return hist
        except Exception:
            pass # 發生錯誤就默默忽略，繼續嘗試下一個後綴
            
    # 如果兩個都失敗，回傳空的 DataFrame
    print(f"      ⚠️ 無法取得 {ticker} 資料 (可能是興櫃股、已下市，或網路異常)")
    return pd.DataFrame()

def main():
    print("===========================================")
    print(f"🛡️ 啟動強韌版爬蟲任務：自動判斷上市櫃、防止 IP 封鎖")
    print("===========================================")

    # ------------------------------------------------
    # 1. 讀取 Google Sheet 現有資料庫
    # ------------------------------------------------
    print("☁️ 階段一：讀取 Google Sheet 現有資料庫...")
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
        all_values = wks.get_all_values()
    except Exception as e:
        print(f"❌ 讀取 Google Sheet 失敗: {e}")
        return
    
    if not all_values:
        return
        
    headers = all_values[0]
    date_idx = headers.index("Date")
    col_idx_map = {name: idx for idx, name in enumerate(headers)}
    
    data_by_date = {}
    for row in all_values[1:]:
        if len(row) > date_idx and row[date_idx]:
            date_str = row[date_idx]
            padded_row = row + [""] * (len(headers) - len(row))
            data_by_date[date_str] = padded_row

    target_tickers = get_tickers_from_headers(headers)
    print(f"   ✅ 追蹤清單共 {len(target_tickers)} 檔股票")

    # ------------------------------------------------
    # 2. 爬取近期資料 (具備防封鎖與智能 fallback)
    # ------------------------------------------------
    print(f"\n🕸️ 階段二：抓取最近 {PERIOD} 資料...")
    
    for idx, ticker in enumerate(target_tickers):
        print(f"   [{idx+1}/{len(target_tickers)}] 正在處理 {ticker}...")
        
        hist = fetch_stock_data(ticker, PERIOD)
        
        if not hist.empty:
            for date_obj, row_data in hist.iterrows():
                date_str = date_obj.strftime("%Y-%m-%d")
                
                if date_str not in data_by_date:
                    new_row = [""] * len(headers)
                    new_row[date_idx] = date_str
                    data_by_date[date_str] = new_row
                
                close_col_name = f"{ticker}_Close"
                if close_col_name in col_idx_map and not pd.isna(row_data['Close']):
                    c_idx = col_idx_map[close_col_name]
                    if data_by_date[date_str][c_idx] == "":
                        data_by_date[date_str][c_idx] = round(row_data['Close'], 2)
                
                vol_col_name = f"{ticker}_Volume"
                if vol_col_name in col_idx_map and not pd.isna(row_data['Volume']):
                    v_idx = col_idx_map[vol_col_name]
                    if data_by_date[date_str][v_idx] == "":
                        data_by_date[date_str][v_idx] = int(row_data['Volume'])
        
        # 【關鍵防護】爬完一檔，睡個幾秒鐘，避免被 Yahoo 封鎖
        time.sleep(DELAY_SECONDS)

    # ------------------------------------------------
    # 3. 排序與寫回
    # ------------------------------------------------
    print("\n🔄 階段三：排序與覆蓋寫回")
    sorted_dates = sorted(data_by_date.keys())
    output_data = [headers]
    
    for d in sorted_dates:
        output_data.append(data_by_date[d])
        
    try:
        wks.clear()
        wks.update(range_name="A1", values=output_data) 
        print(f"   🎉 任務完成！資料已安全同步至 Google Sheet。")
    except Exception as e:
        print(f"❌ 寫回 Google Sheet 失敗: {e}")

if __name__ == "__main__":
    main()
