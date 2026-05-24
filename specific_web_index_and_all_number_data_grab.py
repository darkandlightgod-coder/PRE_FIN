# -*- coding: utf-8 -*-
import os, sys, glob, json, traceback
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 核心邏輯：整合所有 CSV 的公司代號
# ==========================================
def get_all_stock_codes():
    """搜尋所有目標 CSV 並提取所有公司代號"""
    csv_files = glob.glob("*上市*.csv") + glob.glob("*上櫃*.csv") + glob.glob("*興櫃*.csv")
    all_codes = set()
    
    print(f"📂 發現目標 CSV 檔案: {csv_files}")
    for file in csv_files:
        try:
            df = pd.read_csv(file, dtype=str)
            # 尋找含有「代號」或「代碼」的欄位
            code_col = next((col for col in df.columns if '代號' in col or '代碼' in col), df.columns[0])
            # 過濾 4 位數字
            codes = df[code_col].astype(str).str.strip()
            valid_codes = codes[codes.str.match(r'^\d{4}$', na=False)].tolist()
            all_codes.update(valid_codes)
            print(f"✅ 從 {file} 讀取到 {len(valid_codes)} 檔股票")
        except Exception as e:
            print(f"❌ 無法讀取 {file}: {e}")
            
    return sorted(list(all_codes))

# ==========================================
# 2. 爬取與寫入邏輯
# ==========================================
def main():
    # 初始化
    creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
    gc = gspread.authorize(Credentials.from_service_account_info(creds_json))
    sh = gc.open("specific_stock_goods_data")
    wks = sh.sheet1
    
    # 獲取代號清單
    stock_ids = get_all_stock_codes()
    print(f"📊 總計準備爬取 {len(stock_ids)} 檔股票資料...")
    
    # 建立表頭 (Date + N檔股票的 Close/Volume)
    headers = ["Date"]
    for sid in stock_ids:
        headers.extend([f"{sid}_Close", f"{sid}_Volume"])
    
    # 爬取資料 (近 5 日)
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 為了防止一次下載太多，分組處理
    chunk_size = 50
    final_df = pd.DataFrame()
    
    for i in range(0, len(stock_ids), chunk_size):
        subset = [f"{sid}.TW" for sid in stock_ids[i:i+chunk_size]]
        print(f"🕷️ 正在爬取第 {i+1} 至 {i+len(subset)} 檔...")
        data = yf.download(subset, start=start_date, end=end_date, progress=False)
        
        # 處理資料並合併
        for sid in stock_ids[i:i+chunk_size]:
            ticker = f"{sid}.TW"
            if 'Close' in data.columns:
                close_data = data['Close'][ticker]
                vol_data = data['Volume'][ticker]
                # 簡單合併到 DataFrame
                if final_df.empty:
                    final_df = pd.DataFrame({'Date': close_data.index.strftime('%Y-%m-%d')})
                final_df[f"{sid}_Close"] = close_data.values
                final_df[f"{sid}_Volume"] = vol_data.values
    
    # 寫入 Google Sheet
    print("☁️ 正在更新 Google Sheet...")
    data_to_write = [headers] + final_df.fillna(0).astype(str).values.tolist()
    wks.update("A1", data_to_write)
    print("✅ 全部完成！")

if __name__ == "__main__":
    main()
