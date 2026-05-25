# -*- coding: utf-8 -*-
import os
import json
import math
import gspread
import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
PERIOD = "5y"  # 抓取 5 年資料

def get_tickers_from_headers(headers):
    """
    掃描表頭，自動提取所有股票代號。
    例如從 '1101_Close', '2330_Volume' 中提取出 ['1101', '2330']
    """
    tickers = set()
    for header in headers:
        if header.endswith("_Close") or header.endswith("_Volume"):
            ticker = header.split('_')[0]
            tickers.add(ticker)
    return sorted(list(tickers))

def main():
    print("===========================================")
    print(f"🚀 啟動任務：動態偵測欄位，爬取近 {PERIOD} 歷史資料並批次更新")
    print("===========================================")

    # ------------------------------------------------
    # 1. 連線並讀取現有所有資料
    # ------------------------------------------------
    print("\n☁️ 階段一：連線 Google Sheet 並下載現有資料")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
    if not creds_json:
        print("❌ 找不到 GSPREAD_CREDENTIALS 環境變數，請確認金鑰已設定。")
        return
        
    credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(credentials)
    
    try:
        sh = gc.open(SHEET_NAME)
        wks = sh.sheet1
    except Exception as e:
        print(f"❌ 開啟試算表失敗: {e}")
        return

    # 獲取整張表的所有資料
    all_values = wks.get_all_values()
    if not all_values:
        print("❌ 試算表是空的，請至少建立包含 Date 和目標股票欄位的表頭。")
        return

    headers = all_values[0]
    if "Date" not in headers:
        print("❌ 表頭找不到 'Date' 欄位，請確認格式。")
        return

    date_idx = headers.index("Date")
    col_idx_map = {name: idx for idx, name in enumerate(headers)}
    
    # 建立本地記憶體資料庫字典：以 YYYY-MM-DD 為 key
    data_by_date = {}
    for row in all_values[1:]:
        if len(row) > date_idx and row[date_idx]:
            date_str = row[date_idx]
            # 確保列長度與表頭一致，不足的補空字串
            padded_row = row + [""] * (len(headers) - len(row))
            data_by_date[date_str] = padded_row

    # ------------------------------------------------
    # 2. 分析要爬取的股票清單
    # ------------------------------------------------
    target_tickers = get_tickers_from_headers(headers)
    if not target_tickers:
        print("❌ 表頭中未發現符合格式 (例如：2330_Close) 的欄位。")
        return
        
    print(f"   ✅ 偵測到需更新的股票清單: {target_tickers}")

    # ------------------------------------------------
    # 3. 利用 yfinance 爬取五年資料並合併至本地記憶體
    # ------------------------------------------------
    print("\n🕸️ 階段二：拉取歷史資料並進行本地合併 (這可能需要幾分鐘...)")
    
    for ticker in target_tickers:
        ticker_symbol = f"{ticker}.TW"
        print(f"   📈 正在下載 {ticker_symbol} 過去 {PERIOD} 資料...")
        
        try:
            hist = yf.Ticker(ticker_symbol).history(period=PERIOD)
            
            if hist.empty:
                print(f"      ⚠️ {ticker_symbol} 查無資料，可能已下市或代號錯誤 (嘗試改用 .TWO 嗎？)。")
                continue
                
            # 遍歷回傳的每一天
            for date_obj, row_data in hist.iterrows():
                date_str = date_obj.strftime("%Y-%m-%d")
                
                # 如果這一天還不在我們的資料庫裡，建立新的一列
                if date_str not in data_by_date:
                    new_row = [""] * len(headers)
                    new_row[date_idx] = date_str
                    data_by_date[date_str] = new_row
                
                # 更新收盤價
                close_col_name = f"{ticker}_Close"
                if close_col_name in col_idx_map and not pd.isna(row_data['Close']):
                    c_idx = col_idx_map[close_col_name]
                    data_by_date[date_str][c_idx] = round(row_data['Close'], 2)
                
                # 更新交易量
                vol_col_name = f"{ticker}_Volume"
                if vol_col_name in col_idx_map and not pd.isna(row_data['Volume']):
                    v_idx = col_idx_map[vol_col_name]
                    data_by_date[date_str][v_idx] = int(row_data['Volume'])

            print(f"      ✅ {ticker_symbol} 處理完成，共 {len(hist)} 筆資料。")
            
        except Exception as e:
            print(f"      ❌ 下載或處理 {ticker_symbol} 時發生錯誤: {e}")

    # ------------------------------------------------
    # 4. 依照日期排序並轉回二維陣列
    # ------------------------------------------------
    print("\n🔄 階段三：資料排序與格式化")
    sorted_dates = sorted(data_by_date.keys())
    output_data = [headers]
    
    for d in sorted_dates:
        # 確保要上傳的資料沒有 NaN (gspread 不接受 pandas NaN)
        cleaned_row = ["" if pd.isna(val) else val for val in data_by_date[d]]
        output_data.append(cleaned_row)
        
    print(f"   ✅ 資料整理完畢，總計 {len(output_data) - 1} 個交易日。")

    # ------------------------------------------------
    # 5. 批次寫入 Google Sheet
    # ------------------------------------------------
    print("\n✍️ 階段四：批次寫回 Google Sheet")
    try:
        wks.clear()  # 先清空舊資料
        # 一次性更新所有資料，避免 API rate limit
        wks.update(range_name="A1", values=output_data) 
        print(f"   🎉 大功告成！已成功寫入所有歷史資料至 {SHEET_NAME}。")
    except Exception as e:
        print(f"❌ 寫回 Google Sheet 時發生錯誤: {e}")

if __name__ == "__main__":
    main()
