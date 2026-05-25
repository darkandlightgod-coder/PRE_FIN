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
SHEET_NAME = "global_market_factors"
PERIOD = "5y"  # 初始抓取五年資料

# 預設要抓取的全球市場指標 (共 19 項)
TARGET_TICKERS = [
    # --- 全球主要指數與風險指標 ---
    "^GSPC",     # S&P 500 指數
    "^IXIC",     # 那斯達克綜合指數
    "^DJI",      # 道瓊工業指數
    "^SOX",      # 費城半導體指數
    "^VIX",      # VIX 恐慌指數
    
    # --- 總體經濟與債券 ---
    "^TNX",      # 美國 10 年期公債殖利率
    "DX-Y.NYB",  # 美元指數
    
    # --- 能源與貴金屬 ---
    "GC=F",      # 黃金期貨
    "CL=F",      # 原油期貨 (WTI)
    
    # --- 食物與農產品期貨 ---
    "ZC=F",      # 玉米期貨 (Corn)
    "ZW=F",      # 小麥期貨 (Wheat)
    "ZS=F",      # 黃豆期貨 (Soybean)
    
    # --- 運價指標 ---
    "BDRY",      # 波羅的海乾散貨 ETF (運價 BDI 的最佳替代指標)
    
    # --- 重要匯率 (對美元) ---
    "TWD=X",     # 美元兌台幣
    "EURUSD=X",  # 歐元兌美元
    "JPY=X",     # 美元兌日圓
    "CNY=X",     # 美元兌人民幣
    
    # --- 虛擬貨幣 ---
    "BTC-USD",   # 比特幣
    "ETH-USD"    # 以太幣
]

def extract_series_safely(df, ticker, is_multi):
    """安全地從 Yahoo 批次下載的 DataFrame 中提取單一指標的收盤價與成交量"""
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    
    try:
        if is_multi:
            close_s = df['Close'][ticker] if 'Close' in df else pd.Series(dtype=float)
            vol_s = df['Volume'][ticker] if 'Volume' in df else pd.Series(dtype=float)
        else:
            close_s = df['Close'] if 'Close' in df else pd.Series(dtype=float)
            vol_s = df['Volume'] if 'Volume' in df else pd.Series(dtype=float)
        return close_s, vol_s
    except Exception:
        return pd.Series(dtype=float), pd.Series(dtype=float)

def main():
    print("===========================================")
    print(f"🌍 啟動【全球市場因子】進階初始化建置任務 (期間: {PERIOD})")
    print("===========================================")

    # ------------------------------------------------
    # 1. 自動生成表頭 (Headers)
    # ------------------------------------------------
    print(f"📝 階段一：正在自動生成 {len(TARGET_TICKERS)} 項指標的表頭結構...")
    headers = ["Date"]
    for ticker in TARGET_TICKERS:
        headers.append(f"{ticker}_Close")
        headers.append(f"{ticker}_Volume")
    
    col_idx_map = {name: idx for idx, name in enumerate(headers)}
    data_by_date = {}

    # ------------------------------------------------
    # 2. 批次下載五年歷史資料
    # ------------------------------------------------
    print(f"\n🕸️ 階段二：光速向 Yahoo 請求 {len(TARGET_TICKERS)} 檔指標近 {PERIOD} 的歷史數據...")
    df_bulk = yf.download(TARGET_TICKERS, period=PERIOD, threads=True, progress=False)
    is_multi = len(TARGET_TICKERS) > 1

    # ------------------------------------------------
    # 3. 處理資料並寫入記憶體陣列
    # ------------------------------------------------
    print("\n🧠 階段三：資料清洗與對齊中...")
    for ticker in TARGET_TICKERS:
        close_series, vol_series = extract_series_safely(df_bulk, ticker, is_multi)
        
        close_series = close_series.dropna()
        vol_series = vol_series.dropna()
        
        for date_obj, close_val in close_series.items():
            date_str = date_obj.strftime("%Y-%m-%d")
            
            # 建立空列
            if date_str not in data_by_date:
                data_by_date[date_str] = [""] * len(headers)
                data_by_date[date_str][0] = date_str  # Date
            
            # 填入收盤價 (保留四位小數，因應匯率與殖利率的細微變動)
            c_idx = col_idx_map[f"{ticker}_Close"]
            data_by_date[date_str][c_idx] = round(close_val, 4)
            
            # 填入交易量
            if date_obj in vol_series:
                v_idx = col_idx_map[f"{ticker}_Volume"]
                vol_val = vol_series[date_obj]
                # 許多匯率或指數沒有實際成交量，避免寫入無效值或 NaN
                if pd.notna(vol_val) and vol_val > 0:
                    data_by_date[date_str][v_idx] = int(vol_val)

    # ------------------------------------------------
    # 4. 連線 Google Sheet 並強制覆蓋寫入
    # ------------------------------------------------
    print("\n☁️ 階段四：連線 Google Sheet 並寫入資料...")
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
    except Exception as e:
        print(f"❌ 讀取失敗，請確認已在 Google Drive 建立名為 '{SHEET_NAME}' 的試算表。錯誤: {e}")
        return

    # 排序資料
    sorted_dates = sorted(data_by_date.keys())
    output_data = [headers]
    for d in sorted_dates:
        output_data.append(data_by_date[d])
        
    try:
        print("   正在清空舊表並寫入全新的 5 年巨量資料 (這可能需要幾秒鐘)...")
        wks.clear()
        wks.update(range_name="A1", values=output_data) 
        print(f"   🎉 任務完成！共寫入 {len(output_data)} 列資料。您的 Google Sheet 已升級為全球總經資料庫！")
    except Exception as e:
        print(f"❌ 寫回 Google Sheet 失敗: {e}")

if __name__ == "__main__":
    main()
