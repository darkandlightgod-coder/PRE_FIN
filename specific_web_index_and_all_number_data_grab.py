# -*- coding: utf-8 -*-
import os
import json
import pandas as pd
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
# 每日更新只需要抓最近 1 個月的資料，即可涵蓋「最新日期」與「近期空值補完」
PERIOD = "1mo" 

def get_tickers_from_headers(headers):
    """掃描表頭，自動提取所有股票代號"""
    tickers = set()
    for header in headers:
        if header.endswith("_Close") or header.endswith("_Volume"):
            ticker = header.split('_')[0]
            tickers.add(ticker)
    return sorted(list(tickers))

def main():
    print("===========================================")
    print(f"🌞 啟動例行任務：動態偵測欄位，更新近 {PERIOD} 資料與修補空值")
    print("===========================================")

    # ------------------------------------------------
    # 1. 連線並讀取現有所有資料 (作為基底)
    # ------------------------------------------------
    print("☁️ 階段一：讀取 Google Sheet 現有資料庫...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
    credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(credentials)
    
    sh = gc.open(SHEET_NAME)
    wks = sh.sheet1
    all_values = wks.get_all_values()
    
    headers = all_values[0]
    date_idx = headers.index("Date")
    col_idx_map = {name: idx for idx, name in enumerate(headers)}
    
    # 建立記憶體映射
    data_by_date = {}
    for row in all_values[1:]:
        if len(row) > date_idx and row[date_idx]:
            date_str = row[date_idx]
            padded_row = row + [""] * (len(headers) - len(row))
            data_by_date[date_str] = padded_row

    target_tickers = get_tickers_from_headers(headers)
    print(f"   ✅ 追蹤清單: {target_tickers}")

    # ------------------------------------------------
    # 2. 爬取近期資料，進行智能補完與新增 (rbind 概念)
    # ------------------------------------------------
    print(f"\n🕸️ 階段二：抓取最近 {PERIOD} 資料，進行比對與修補...")
    
    for ticker in target_tickers:
        ticker_symbol = f"{ticker}.TW"
        
        try:
            hist = yf.Ticker(ticker_symbol).history(period=PERIOD)
            if hist.empty: continue
                
            for date_obj, row_data in hist.iterrows():
                date_str = date_obj.strftime("%Y-%m-%d")
                
                # 如果是全新的日期，建立空列 (等同於 rbind 新增列)
                if date_str not in data_by_date:
                    new_row = [""] * len(headers)
                    new_row[date_idx] = date_str
                    data_by_date[date_str] = new_row
                
                # 檢查並更新收盤價 (遇到空值或新日期就填入)
                close_col_name = f"{ticker}_Close"
                if close_col_name in col_idx_map and not pd.isna(row_data['Close']):
                    c_idx = col_idx_map[close_col_name]
                    # 如果原本是空的，或者我們想強制更新近期的值，就寫入
                    if data_by_date[date_str][c_idx] == "":
                        data_by_date[date_str][c_idx] = round(row_data['Close'], 2)
                
                # 檢查並更新交易量
                vol_col_name = f"{ticker}_Volume"
                if vol_col_name in col_idx_map and not pd.isna(row_data['Volume']):
                    v_idx = col_idx_map[vol_col_name]
                    if data_by_date[date_str][v_idx] == "":
                        data_by_date[date_str][v_idx] = int(row_data['Volume'])

        except Exception as e:
            print(f"      ❌ 處理 {ticker_symbol} 時發生錯誤: {e}")

    # ------------------------------------------------
    # 3. 依照日期排序並一次性寫回
    # ------------------------------------------------
    print("\n🔄 階段三：排序與覆蓋寫回")
    # 這裡的排序會確保最新的日期永遠跑到「最下方」
    sorted_dates = sorted(data_by_date.keys())
    output_data = [headers]
    
    for d in sorted_dates:
        output_data.append(data_by_date[d])
        
    wks.clear()
    wks.update(range_name="A1", values=output_data) 
    print(f"   🎉 每日更新完成！新資料已加至最下方，且近期空值已修補。")

if __name__ == "__main__":
    main()
