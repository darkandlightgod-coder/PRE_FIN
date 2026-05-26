# -*- coding: utf-8 -*-
"""
負責抓取全球大盤指數、總體經濟、原物料等宏觀數據。
寫入目標：global_market_factors (獨立分頁)
"""
import os
import json
import pandas as pd
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

CONFIG = {
    "SPREADSHEET_ID": "1ZVmajxud7D4uRim8qKPRM4bA_TjnZOxvaZsWja3FKeM",
    "SHEET_NAME": "global_market_factors", # 已更新為正確分頁名稱
    "PERIOD": "5y",
    "TARGET_TICKERS": [
        "^GSPC", "^IXIC", "^DJI", "^SOX", "^VIX",
        "^TNX", "DX-Y.NYB", "GC=F", "CL=F",
        "ZC=F", "ZW=F", "ZS=F", "BDRY",
        "TWD=X", "EURUSD=X", "JPY=X", "CNY=X",
        "BTC-USD", "ETH-USD"
    ]
}

def extract_series(df, ticker, is_multi):
    if df.empty: return pd.Series(dtype=float), pd.Series(dtype=float)
    try:
        if is_multi:
            return (df['Close'][ticker] if 'Close' in df else pd.Series(dtype=float), 
                    df['Volume'][ticker] if 'Volume' in df else pd.Series(dtype=float))
        return (df['Close'] if 'Close' in df else pd.Series(dtype=float), 
                df['Volume'] if 'Volume' in df else pd.Series(dtype=float))
    except: return pd.Series(dtype=float), pd.Series(dtype=float)

def main():
    print(f"🌍 啟動【全球市場因子】抓取任務 (期間: {CONFIG['PERIOD']})")
    
    df_bulk = yf.download(CONFIG['TARGET_TICKERS'], period=CONFIG['PERIOD'], threads=True, progress=False)
    merged_df = pd.DataFrame(index=df_bulk.index)
    
    for ticker in CONFIG['TARGET_TICKERS']:
        c_series, v_series = extract_series(df_bulk, ticker, len(CONFIG['TARGET_TICKERS']) > 1)
        merged_df[f"{ticker}_Close"] = c_series
        merged_df[f"{ticker}_Volume"] = v_series

    close_cols = [c for c in merged_df.columns if c.endswith("_Close")]
    vol_cols = [c for c in merged_df.columns if c.endswith("_Volume")]
    merged_df[close_cols] = merged_df[close_cols].round(4)
    
    merged_df.index.name = 'Date'
    merged_df = merged_df.reset_index()
    merged_df['Date'] = pd.to_datetime(merged_df['Date']).dt.strftime('%Y-%m-%d')
    
    for col in vol_cols:
        merged_df[col] = merged_df[col].apply(lambda x: int(x) if pd.notnull(x) else "")
    merged_df = merged_df.fillna("")
    
    output_data = [merged_df.columns.tolist()] + merged_df.values.tolist()

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
        gc = gspread.authorize(Credentials.from_service_account_info(creds, scopes=scopes))
        
        # 寫入指定的獨立分頁
        wks = gc.open_by_key(CONFIG['SPREADSHEET_ID']).worksheet(CONFIG['SHEET_NAME'])
        wks.clear()
        wks.update("A1", output_data) 
        print(f"🎉 {CONFIG['SHEET_NAME']} 更新完成！")
    except Exception as e:
        print(f"❌ 寫入失敗: {e}")

if __name__ == "__main__":
    main()
