# -*- coding: utf-8 -*-
"""
v10.0 GLOBAL_Market_Factors.py
負責抓取過去5年至今的國際宏觀因子與美股目標，寫入 global_market_factors
"""
import os, sys, json, traceback
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

MACRO_TICKERS = {
    "^TWII": "TWII", "GC=F": "Gold", "^TNX": "US10Y", "^VIX": "VIX", 
    "^SOX": "SOX", "^GSPC": "SP500", "CL=F": "CrudeOil", "ZC=F": "Corn", "BDRY": "BDI",
    "NVDA": "NVDA", "TSLA": "TSLA", "INTC": "INTC", 
    "AAPL": "AAPL", "MSFT": "MSFT", "AMZN": "AMZN", "LLY": "LLY", 
    "NVO": "NVO", "7203.T": "Toyota"
}

def get_gspread_client():
    try:
        creds_json = os.environ.get("GSPREAD_CREDENTIALS")
        if not creds_json: raise ValueError("找不到 Secret: GSPREAD_CREDENTIALS")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))
    except Exception as e:
        print(f"❌ Google 授權失敗: {e}")
        return None

def get_target_spreadsheet(gc):
    files = gc.list_spreadsheet_files()
    if not files: raise Exception("該服務帳號下找不到任何試算表，請先分享一個 Google Sheet 給服務帳號")
    return files[0]['id']

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df=None):
    try:
        sh = gc.open_by_key(spreadsheet_id)
        wks = sh.worksheet(sheet_name)
    except Exception as e:
        print(f"❌ 錯誤: 找不到分頁 '{sheet_name}' (請先在雲端手動建立): {e}")
        return

    try:
        if df is None or df.empty: return
        df_clean = df.fillna("")
        if 'Date' in df_clean.columns and pd.api.types.is_datetime64_any_dtype(df_clean['Date']):
            df_clean['Date'] = df_clean['Date'].dt.strftime("%Y-%m-%d")
        
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 初次寫入 {len(df_clean)} 筆至 {sheet_name}")
        else:
            existing_dates = set([row[0] for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty:
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 附加 {len(df_new)} 筆新資料至 {sheet_name}")
            else:
                print(f"⚡ {sheet_name} 已是最新，無缺漏需補完")
    except Exception as e:
        print(f"❌ 寫入 {sheet_name} 異常: {e}")

def main():
    print("="*50 + "\n🚀 v10.0 [模組 1] 國際金融指標採集\n" + "="*50)
    gc = get_gspread_client()
    if not gc: return
    sp_id = get_target_spreadsheet(gc)
    
    start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    print(f"🌍 正在採集國際指標 (回溯 5 年至 {start_date})...")
    
    try:
        df_macro = yf.download(list(MACRO_TICKERS.keys()), start=start_date, progress=False)['Close']
        df_macro.rename(columns=MACRO_TICKERS, inplace=True)
        df_macro = df_macro.ffill().dropna(how='all').reset_index()
        df_macro.rename(columns={'index': 'Date'}, inplace=True)
        
        safe_gspread_write(gc, sp_id, "global_market_factors", df_macro)
    except Exception as e:
        print("❌ 獲取國際市場特徵失敗:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
