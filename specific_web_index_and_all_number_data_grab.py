# -*- coding: utf-8 -*-
import os, json
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from gspread.utils import rowcol_to_a1

# ==========================================
# 參數設定區
# ==========================================
TARGET_STOCK = "2330"
SHEET_NAME = "taifex_derivatives_history"

def get_last_friday():
    """計算上週五的日期"""
    today = datetime.now()
    # weekday() 回傳 0-6 (週一至週日)。週五是 4。
    # 計算今天距離上週五差幾天
    offset = (today.weekday() - 4) % 7
    if offset == 0:
        offset = 7 # 如果今天就是週五，我們抓「上週五」的資料
        
    last_friday = today - timedelta(days=offset)
    return last_friday

def main():
    print("===========================================")
    print(f"🚀 啟動任務：依據 Google Sheet 欄位，爬取並更新 {TARGET_STOCK} 上週五資料")
    print("===========================================")

    # ------------------------------------------------
    # 1. 連線至 Google Sheet 並讀取表頭
    # ------------------------------------------------
    print("☁️ 階段一：連線至 Google Sheet 讀取現有架構")
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

    # 獲取第一列 (表頭) 和第一欄 (日期)
    headers = wks.row_values(1)
    date_col_values = wks.col_values(1)
    
    close_col_name = f"{TARGET_STOCK}_Close"
    vol_col_name = f"{TARGET_STOCK}_Volume"
    
    if close_col_name not in headers or vol_col_name not in headers:
        print(f"❌ 在試算表中找不到 {TARGET_STOCK} 的對應欄位 ({close_col_name} 或 {vol_col_name})。")
        return

    # 找出欄位索引 (0-indexed，但 Google Sheet 是 1-indexed)
    date_idx = headers.index("Date")
    close_idx = headers.index(close_col_name)
    vol_idx = headers.index(vol_col_name)
    
    print(f"   ✅ 成功定位欄位！")
    print(f"      - Date 在第 {date_idx + 1} 欄")
    print(f"      - {close_col_name} 在第 {close_idx + 1} 欄")
    print(f"      - {vol_col_name} 在第 {vol_idx + 1} 欄")

    # ------------------------------------------------
    # 2. 計算日期並利用 yfinance 爬取資料
    # ------------------------------------------------
    print("\n🕸️ 階段二：計算日期與爬取股價資料")
    last_friday = get_last_friday()
    target_date_str = last_friday.strftime('%Y-%m-%d')
    print(f"   📅 目標日期 (上週五): {target_date_str}")
    
    # yfinance 需要 end date 為目標日的「下一天」，這樣才抓得到目標日當天
    next_day = last_friday + timedelta(days=1)
    end_date_str = next_day.strftime('%Y-%m-%d')
    
    ticker_symbol = f"{TARGET_STOCK}.TW" # 預設當作上市股票
    print(f"   📈 正在透過 yfinance 獲取 {ticker_symbol} 資料...")
    
    hist = yf.Ticker(ticker_symbol).history(start=target_date_str, end=end_date_str)
    
    if hist.empty:
        print(f"   ⚠️ 找不到 {ticker_symbol} 在 {target_date_str} 的交易資料 (可能休市)。")
        return
        
    close_val = round(hist['Close'].iloc[0], 2)
    vol_val = int(hist['Volume'].iloc[0])
    print(f"   ✅ 獲取成功！收盤價: {close_val}, 交易量: {vol_val}")

    # ------------------------------------------------
    # 3. 將資料精準寫入 Google Sheet
    # ------------------------------------------------
    print("\n✍️ 階段三：更新至 Google Sheet")
    
    try:
        if target_date_str in date_col_values:
            # 日期已存在，更新特定儲存格
            row_num = date_col_values.index(target_date_str) + 1
            print(f"   📝 發現 {target_date_str} 已存在於第 {row_num} 列，進行儲存格更新...")
            
            # 使用 A1 標記法更新 (例如 C2, D2)
            close_cell = rowcol_to_a1(row_num, close_idx + 1)
            vol_cell = rowcol_to_a1(row_num, vol_idx + 1)
            
            wks.update(range_name=close_cell, values=[[close_val]])
            wks.update(range_name=vol_cell, values=[[vol_val]])
            print(f"   ✅ 儲存格 {close_cell} 與 {vol_cell} 更新完畢！")
            
        else:
            # 日期不存在，新增一整列
            print(f"   ➕ 找不到 {target_date_str}，準備新增一列...")
            new_row = [""] * len(headers)
            new_row[date_idx] = target_date_str
            new_row[close_idx] = close_val
            new_row[vol_idx] = vol_val
            
            wks.append_row(new_row)
            print(f"   ✅ 已成功將 {target_date_str} 的資料作為新列附加至試算表底部！")
            
    except Exception as e:
        print(f"❌ 寫入資料時發生錯誤: {e}")

if __name__ == "__main__":
    main()
