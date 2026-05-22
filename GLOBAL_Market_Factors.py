# -*- coding: utf-8 -*-
"""
v10.0 GLOBAL_Market_Factors.py
【第三步】：國際金融指標與 13 檔國際標的數據採集
"""
import os, sys, json, traceback
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

MACRO_TICKERS = {
    "^TWII": "TWII", "GC=F": "Gold", "^TNX": "US10Y", "^VIX": "VIX", 
    "^SOX": "SOX", "NVDA": "NVDA", "TSLA": "TSLA", "INTC": "INTC", 
    "AAPL": "AAPL", "MSFT": "MSFT", "AMZN": "AMZN", "LLY": "LLY", 
    "NVO": "NVO", "7203.T": "Toyota"
}

def get_moat_sheet():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(gc.list_spreadsheet_files()[0]['id'])

def smart_append(sh, sheet_name, df):
    if df.empty: return
    try:
        try: wks = sh.worksheet(sheet_name)
        except: wks = sh.add_worksheet(title=sheet_name, rows="1000", cols="30")
        df = df.fillna("")
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            df = df.rename(columns={'index': 'Date', 'Date': 'Date'})
        if 'Date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['Date']):
            df['Date'] = df['Date'].dt.strftime("%Y-%m-%d")

        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df.columns.values.tolist()] + df.values.tolist())
        else:
            existing_dates = set([row[0] for row in existing[1:] if row])
            if 'Date' in df.columns:
                df = df[~df['Date'].isin(existing_dates)]
            if not df.empty: wks.append_rows(df.values.tolist())
    except Exception as e:
        traceback.print_exc()

def main():
    print("="*50 + "\n🚀 v10.0 [3/5] 全球總經與美股標的採集\n" + "="*50)
    sh = get_moat_sheet()
    
    start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    print(f"🌍 正在採集國際指標 (回溯至 {start_date})...")
    
    try:
        df_macro = yf.download(list(MACRO_TICKERS.keys()), start=start_date, progress=False)['Close']
        df_macro.rename(columns=MACRO_TICKERS, inplace=True)
        df_macro = df_macro.ffill().dropna(how='all')
        
        smart_append(sh, "global_market_factors", df_macro)
        print(f"✅ 全球指標獲取成功，共 {len(df_macro)} 筆。")
    except Exception as e:
        print("❌ 獲取國際市場特徵失敗:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
