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
    "^GSPC", "^IXIC", "^DJI", "^SOX", "^VIX",
    # --- 總體經濟與債券 ---
    "^TNX", "DX-Y.NYB",
    # --- 能源與貴金屬 ---
    "GC=F", "CL=F",
    # --- 食物與農產品期貨 ---
    "ZC=F", "ZW=F", "ZS=F",
    # --- 運價指標 ---
    "BDRY",
    # --- 重要匯率 (對美元) ---
    "TWD=X", "EURUSD=X", "JPY=X", "CNY=X",
    # --- 虛擬貨幣 ---
    "BTC-USD", "ETH-USD"
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
    print(f"🌍 啟動【全球市場因子】無空值初始化任務 (期間: {PERIOD})")
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
    # 建立一個以所有抓取到的日期為基礎的 DataFrame (包含假日，因為 Crypto 有假日資料)
    merged_df = pd.DataFrame(index=df_bulk.index)
    
    for ticker in TARGET_TICKERS:
        close_series, vol_series = extract_series_safely(df_bulk, ticker, is_multi)
        merged_df[f"{ticker}_Close"] = close_series
        merged_df[f"{ticker}_Volume"] = vol_series

    # ------------------------------------------------
    # 3. 處理空值 (Holidays / Weekends) - 關鍵優化
    # ------------------------------------------------
    print("✨ 階段三：執行假日空值填補 (前向填充與補零)...")
    
    close_cols = [c for c in merged_df.columns if c.endswith("_Close")]
    vol_cols = [c for c in merged_df.columns if c.endswith("_Volume")]

    # 針對收盤價：使用前向填充 (ffill)，假日沿用上一個交易日的價格
    merged_df[close_cols] = merged_df[close_cols].ffill()
    # 防呆機制：如果一開始的前幾天就是假日，用後向填充補齊
    merged_df[close_cols] = merged_df[close_cols].bfill()
    # 數值四捨五入到小數點後 4 位
    merged_df[close_cols] = merged_df[close_cols].round(4)

    # 針對交易量：假日的交易量直接補 0
    merged_df[vol_cols] = merged_df[vol_cols].fillna(0)
    
    # 將剩下的任何極端例外 NaN 轉為空字串，以防萬一
    merged_df = merged_df.fillna("")

    # ------------------------------------------------
    # 4. 格式化輸出資料
    # ------------------------------------------------
    print("📋 階段四：轉換為 Google Sheet 寫入格式...")
    # 把 Date 從 Index 變成普通的欄位
    merged_df = merged_df.reset_index()
    # 將日期格式化為字串 YYYY-MM-DD
    merged_df['Date'] = merged_df['Date'].dt.strftime('%Y-%m-%d')
    
    # 將部分交易量因為含 NaN 變成 float 的欄位，轉回整數 (0)
    for col in vol_cols:
        merged_df[col] = pd.to_numeric(merged_df[col], errors='ignore')
        # 如果該欄位都是數字，就轉為整數
        if pd.api.types.is_numeric_dtype(merged_df[col]):
            merged_df[col] = merged_df[col].astype(int)

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
    except Exception as e:
        print(f"❌ 讀取失敗，請確認已在 Google Drive 建立名為 '{SHEET_NAME}' 的試算表。錯誤: {e}")
        return

    try:
        print("   正在清空舊表並寫入全新的巨量資料...")
        wks.clear()
        wks.update(range_name="A1", values=output_data) 
        print(f"   🎉 任務完成！共寫入 {len(output_data)} 列無空值的連續資料！")
    except Exception as e:
        print(f"❌ 寫回 Google Sheet 失敗: {e}")

if __name__ == "__main__":
    main()
