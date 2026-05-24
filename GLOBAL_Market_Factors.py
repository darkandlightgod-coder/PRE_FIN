# -*- coding: utf-8 -*-
import os, sys, json, traceback, time
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, file_name, df):
    """【獨立檔案寫入邏輯】：依據檔名開啟獨立的 Google Sheet 檔案"""
    try:
        sh = gc.open(file_name)
        wks = sh.sheet1 # 永遠寫入該檔案的第一個預設分頁
        if df.empty: return
        
        # 強制字串化防護，阻絕 Timestamp/NaN 序列化崩潰
        df_clean = df.copy()
        if 'Date' in df_clean.columns and pd.api.types.is_datetime64_any_dtype(df_clean['Date']):
            df_clean['Date'] = df_clean['Date'].dt.strftime("%Y-%m-%d")
        df_clean = df_clean.astype(str).replace({"nan": "", "NaN": "", "NaT": "", "None": "", "<NA>": ""})
        
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 檔案 [{file_name}] 初始化成功")
        else:
            existing_dates = set([str(row[0]) for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty:
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 附加 {len(df_new)} 筆至檔案 [{file_name}]")
            else:
                print(f"⚡ 檔案 [{file_name}] 已是最新的")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ 錯誤：找不到名為 '{file_name}' 的檔案！(請確認是否已建立並共用給服務帳號)")
    except Exception as e:
        print(f"❌ 寫入檔案 [{file_name}] 異常:\n{traceback.format_exc()}")

def main():
    print("🌍 啟動國際宏觀因子採集")
    try:
        gc = get_gspread_client()
        tickers = {"^TWII": "TWII", "GC=F": "Gold", "^TNX": "US10Y", "^VIX": "VIX", "^SOX": "SOX", "^GSPC": "SP500"}
        start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
        
        data = yf.download(list(tickers.keys()), start=start_date, progress=False)
        df_macro = data['Close'] if isinstance(data.columns, pd.MultiIndex) else data
        df_macro.rename(columns=tickers, inplace=True)
        df_macro = df_macro.ffill().dropna(how='all').reset_index()
        df_macro.rename(columns={'index': 'Date', 'Date': 'Date'}, inplace=True)
        
        # 寫入指定的獨立檔案
        safe_gspread_write(gc, "global_market_factors", df_macro)
    except Exception as e:
        print(f"❌ 模組崩潰:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
