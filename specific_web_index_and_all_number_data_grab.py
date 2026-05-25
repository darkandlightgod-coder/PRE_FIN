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
    stock_dict = {} # 存放 代號: 後綴
    
    # 篩選條件：包含上市/上櫃/興櫃/公司，但「排除」創櫃與公開發行
    target_files = []
    for f in all_csvs:
        if "創櫃" in f or "公開發行" in f:
            continue
        if "上市" in f or "上櫃" in f or "興櫃" in f or "公司" in f:
            target_files.append(f)

    print(f"🎯 鎖定目標 CSV 檔案 (已排除創櫃/公開發行): {target_files}")

    for file in target_files:
        # 判斷後綴：上市用 .TW，上櫃/興櫃用 .TWO
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
            
        # 清理欄位名稱並尋找「代號」
        df.columns = df.columns.str.strip()
        code_col = next((col for col in df.columns if '代號' in col or '代碼' in col), df.columns[0])
        
        # 提取 4 碼數字
        raw_codes = df[code_col].astype(str).str.strip()
        valid_codes = raw_codes[raw_codes.str.match(r'^\d{4}$', na=False)].tolist()
        
        for code in valid_codes:
            stock_dict[code] = suffix
            
        print(f"   ✅ 從 {file} 讀取並配置了 {len(valid_codes)} 檔股票代號。")

    print(f"🎉 階段一完成：共計獲取 {len(stock_dict)} 檔不重複的股票代號！")
    return stock_dict

# ==========================================
# 2. 爬取與資料整理
# ==========================================
def main():
    # 1. 取得所有代碼與對應的 yfinance 後綴
    stock_dict = get_stock_codes_with_suffix()
    if not stock_dict:
        print("❌ 找不到任何股票代號，程式終止。")
        return

    # 將代號排序，保證每次產生的欄位順序固定
    sorted_codes = sorted(list(stock_dict.keys()))
    
    # 建立表頭：Date, 1101_Close, 1101_Volume, 1102_Close...
    headers = ["Date"]
    for code in sorted_codes:
        headers.extend([f"{code}_Close", f"{code}_Volume"])
        
    print(f"📊 預計生成的 Google Sheet 總欄位數將達: {len(headers)} 欄！")

    # 2. 設定爬取日期區間 (近 5 日)
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") # yfinance end不包含當天，需+1
    
    # 3. 分批爬取資料 (防止 yfinance 拒絕連線)
    chunk_size = 50
    final_df = pd.DataFrame()
    
    print("===========================================")
    print("🕷️ 階段二：開始從 Yahoo Finance 爬取交易資料")
    
    for i in range(0, len(sorted_codes), chunk_size):
        chunk_codes = sorted_codes[i:i+chunk_size]
        # 組裝成帶有後綴的 Ticker (例如 2330.TW, 3105.TWO)
        tickers = [f"{code}{stock_dict[code]}" for code in chunk_codes]
        
        print(f"   ⏳ 正在爬取第 {i+1} 至 {i+len(chunk_codes)} 檔 ({tickers[0]} ~ {tickers[-1]})...")
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)
        
        # 將抓到的資料塞入最終的 DataFrame
        for code in chunk_codes:
            ticker = f"{code}{stock_dict[code]}"
            
            # 安全防禦：如果 yfinance 沒回傳這檔股票，或者欄位不存在，則填 0
            close_val = data['Close'][ticker] if ('Close' in data.columns and ticker in data['Close']) else pd.Series(0, index=data.index)
            vol_val = data['Volume'][ticker] if ('Volume' in data.columns and ticker in data['Volume']) else pd.Series(0, index=data.index)
            
            # 初始化 DataFrame 的 Date 索引
            if final_df.empty and not data.empty:
                final_df = pd.DataFrame({'Date': data.index.strftime('%Y-%m-%d')})
                final_df.set_index('Date', inplace=True)
                
            # 將 Close 與 Volume 加入 DataFrame (確保日期對齊)
            final_df[f"{code}_Close"] = close_val.values if not close_val.empty else 0
            final_df[f"{code}_Volume"] = vol_val.values if not vol_val.empty else 0

    # 重置索引，讓 Date 變回普通欄位
    final_df.reset_index(inplace=True)
    
    # ==========================================
    # 3. 寫入 Google Sheet 邏輯
    # ==========================================
    print("===========================================")
    print("☁️ 階段三：準備寫入 Google Sheet")
    try:
        creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
        gc = gspread.authorize(Credentials.from_service_account_info(creds_json))
        
        # 依照您的要求，寫入名為 taifex_derivatives_history 的試算表
        sh = gc.open("taifex_derivatives_history")
        wks = sh.sheet1
        
        # 【關鍵防禦】因為超過 1000 檔股票會產生 2000 多個欄位，必須先「擴充 Sheet 尺寸」
        data_to_write = [headers] + final_df.fillna(0).astype(str).values.tolist()
        req_rows = len(data_to_write)
        req_cols = len(headers)
        
        print(f"   🧰 正在調整試算表大小至 {req_rows} 列 x {req_cols} 欄...")
        # 動態調整 Google Sheet 大小，防止欄位超出 A-Z 限制而報錯
        wks.resize(rows=max(100, req_rows), cols=req_cols) 
        
        print("   📝 正在清空舊資料並寫入新資料...")
        wks.clear()
        wks.update("A1", data_to_write)
        
        print("✅ 任務圓滿完成！1000+ 股票資料已成功同步至 taifex_derivatives_history！")
        
    except Exception as e:
        print(f"❌ 寫入 Google Sheet 時發生錯誤: {e}")

if __name__ == "__main__":
    main()
