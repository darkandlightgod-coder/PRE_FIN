# -*- coding: utf-8 -*-
import os, sys, glob, json, time
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 核心邏輯：讀取 CSV 並判斷 yfinance 股票代號後綴
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
# 2. 爬取與資料整理 (效能無破碎化優化版)
# ==========================================
def main():
    stock_dict = get_stock_codes_with_suffix()
    if not stock_dict:
        print("❌ 找不到任何股票代號，程式終止。")
        return

    sorted_codes = sorted(list(stock_dict.keys()))
    
    # 建立表頭驗證用
    headers = ["Date"]
    for code in sorted_codes:
        headers.extend([f"{code}_Close", f"{code}_Volume"])
        
    print(f"📊 預計生成的 Google Sheet 總欄位數將達: {len(headers)} 欄！")

    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    chunk_size = 50
    df_list = [] # 🌟 核心修改：用 List 收集各個小塊，避免 Pandas DataFrame 碎片化
    
    print("===========================================")
    print("🕷️ 階段二：開始從 Yahoo Finance 爬取交易資料")
    
    for i in range(0, len(sorted_codes), chunk_size):
        chunk_codes = sorted_codes[i:i+chunk_size]
        tickers = [f"{code}{stock_dict[code]}" for code in chunk_codes]
        
        print(f"   ⏳ 正在爬取第 {i+1} 至 {i+len(chunk_codes)} 檔 ({tickers[0]} ~ {tickers[-1]})...")
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            continue
            
        # 暫存這個區塊的 Series 資料
        chunk_dict = {}
        is_multi_index = isinstance(data.columns, pd.MultiIndex)
        
        for code in chunk_codes:
            ticker = f"{code}{stock_dict[code]}"
            
            # 安全獲取 Series (確保欄位對齊，並防禦 yfinance 回傳結構變化的特例)
            if is_multi_index:
                c_ser = data['Close'][ticker] if ('Close' in data.columns and ticker in data['Close']) else pd.Series(dtype=float)
                v_ser = data['Volume'][ticker] if ('Volume' in data.columns and ticker in data['Volume']) else pd.Series(dtype=float)
            else:
                c_ser = data['Close'] if 'Close' in data.columns else pd.Series(dtype=float)
                v_ser = data['Volume'] if 'Volume' in data.columns else pd.Series(dtype=float)
            
            chunk_dict[f"{code}_Close"] = c_ser
            chunk_dict[f"{code}_Volume"] = v_ser
            
        # 將這個小區塊轉成 DataFrame 並塞入 List
        chunk_df = pd.DataFrame(chunk_dict)
        df_list.append(chunk_df)

    print("===========================================")
    print("🧩 階段二-2：正在一次性合併 1000+ 檔股票的 DataFrame (無破碎化)")
    
    if df_list:
        # 🌟 核心修改：使用 pd.concat() 一次性合併！速度最快且不會報錯
        final_df = pd.concat(df_list, axis=1)
        final_df.fillna(0, inplace=True) # 將 NaN 轉為 0
        
        # 整理 Date 欄位
        final_df.index = final_df.index.strftime('%Y-%m-%d')
        final_df.index.name = 'Date'
        final_df.reset_index(inplace=True)
    else:
        print("⚠️ 警告：無法從 Yahoo 獲取任何資料！")
        final_df = pd.DataFrame(columns=headers)
    
    # 確保最終 DataFrame 欄位順序與 headers 一致 (補齊可能缺失的欄位)
    for col in headers:
        if col not in final_df.columns:
            final_df[col] = 0
    final_df = final_df[headers]

    # ==========================================
    # 3. 寫入 Google Sheet 邏輯
    # ==========================================
    print("===========================================")
    print("☁️ 階段三：準備寫入 Google Sheet")
    try:
        creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
        gc = gspread.authorize(Credentials.from_service_account_info(creds_json))
        
        sh = gc.open("taifex_derivatives_history")
        wks = sh.sheet1
        
        data_to_write = [headers] + final_df.astype(str).values.tolist()
        req_rows = len(data_to_write)
        req_cols = len(headers)
        
        print(f"   🧰 正在調整試算表大小至 {req_rows} 列 x {req_cols} 欄...")
        wks.resize(rows=max(100, req_rows), cols=req_cols) 
        
        print("   📝 正在清空舊資料並寫入新資料...")
        wks.clear()
        wks.update("A1", data_to_write)
        
        print("✅ 任務圓滿完成！1000+ 股票資料已成功同步至 taifex_derivatives_history！")
        
    except Exception as e:
        print(f"❌ 寫入 Google Sheet 時發生錯誤: {e}")

if __name__ == "__main__":
    main()
