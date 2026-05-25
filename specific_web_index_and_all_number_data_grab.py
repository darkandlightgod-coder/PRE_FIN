# -*- coding: utf-8 -*-
import os, sys, glob, json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 核心邏輯：讀取 CSV 並提取股票代號
# ==========================================
def get_stock_codes_with_suffix():
    """
    掃描目標 CSV，排除創櫃與公開發行。
    回傳字典格式： { '2330': '.TW', '3105': '.TWO', ... }
    """
    print("===========================================")
    print("📂 階段一：讀取本地 CSV 並提取股票代號")
    
    all_csvs = glob.glob("*.csv")
    stock_dict = {}
    
    target_files = []
    for f in all_csvs:
        if "創櫃" in f or "公開發行" in f:
            continue
        if "上市" in f or "上櫃" in f or "興櫃" in f or "公司" in f:
            target_files.append(f)

    print(f"🎯 鎖定目標 CSV 檔案 (已排除創櫃/公開發行): {target_files}")

    for file in target_files:
        suffix = ".TW" if "上市" in file else ".TWO"
        
        df = None
        for enc in ['utf-8-sig', 'big5', 'utf-8', 'cp950']:
            try:
                df = pd.read_csv(file, encoding=enc, dtype=str)
                break
            except:
                pass
                
        if df is None:
            print(f"   ❌ 無法讀取 {file}，跳過。")
            continue
            
        df.columns = df.columns.str.strip()
        code_col = next((col for col in df.columns if '代號' in col or '代碼' in col), df.columns[0])
        
        raw_codes = df[code_col].astype(str).str.strip()
        valid_codes = raw_codes[raw_codes.str.match(r'^\d{4}$', na=False)].tolist()
        
        for code in valid_codes:
            stock_dict[code] = suffix
            
        print(f"   ✅ 從 {file} 讀取並配置了 {len(valid_codes)} 檔股票代號。")

    print(f"🎉 階段一完成：共計獲取 {len(stock_dict)} 檔不重複的股票代號！")
    return stock_dict

# ==========================================
# 2. 僅建立欄位並寫入 Google Sheet
# ==========================================
def main():
    stock_dict = get_stock_codes_with_suffix()
    if not stock_dict:
        print("❌ 找不到任何股票代號，程式終止。")
        return

    # 將代碼排序
    sorted_codes = sorted(list(stock_dict.keys()))
    
    # 建立表頭：Date, 1101_Close, 1101_Volume, 1102_Close...
    headers = ["Date"]
    for code in sorted_codes:
        headers.extend([f"{code}_Close", f"{code}_Volume"])
        
    print(f"📊 預計生成的 Google Sheet 總欄位數將達: {len(headers)} 欄！")
    
    print("===========================================")
    print("🛑 應要求：已略過 yfinance 爬蟲階段，直接進入寫入表頭程序。")
    print("===========================================")

    # ==========================================
    # 3. 寫入 Google Sheet 邏輯 (僅寫入第一列)
    # ==========================================
    print("☁️ 階段三：準備寫入 Google Sheet")
    try:
        data_to_write = [headers]
        req_cols = len(headers)
        
        # 🌟 核心修復：宣告需要的 Google API 權限範圍 (Scopes)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 載入金鑰並綁定 Scopes
        creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
        credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
        gc = gspread.authorize(credentials)
        
        # 開啟試算表
        sh = gc.open("taifex_derivatives_history")
        wks = sh.sheet1
        
        print(f"   🧰 正在調整試算表大小，確保能容納 {req_cols} 個欄位...")
        wks.resize(rows=100, cols=req_cols) 
        
        print("   📝 正在清空舊資料並寫入 1000+ 檔股票的「全新表頭」...")
        wks.clear()
        wks.update("A1", data_to_write)
        
        print("✅ 任務圓滿完成！請前往 Google Sheet 確認數千個欄位是否已成功建立！")
        
    except Exception as e:
        print(f"❌ 寫入 Google Sheet 時發生錯誤: {e}")

if __name__ == "__main__":
    main()
