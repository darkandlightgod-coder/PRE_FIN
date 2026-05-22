# -*- coding: utf-8 -*-
"""
V10.1 GLOBAL_Market_Factors.py
維持原始環境自癒架構，加入極強防護的寫入機制與全域除錯。
"""
import os, sys, subprocess, traceback, importlib, time, json, requests, urllib3
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 【1. 環境自建環境自癒系統】(維持您原有的架構)
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 GLOBAL_Market_Factors 環境檢測...")
    dependencies = {"pandas": "pandas", "yfinance": "yfinance", "gspread": "gspread", "google-auth": "google-auth"}
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
bootstrap()

# ==========================================
# 【2. 安全寫入與爬蟲邏輯】
# ==========================================
MACRO_TICKERS = {
    "^TWII": "TWII", "GC=F": "Gold", "^TNX": "US10Y", "^VIX": "VIX", 
    "^SOX": "SOX", "^GSPC": "SP500"
}

def get_gspread_client():
    try:
        creds_json = os.environ.get("GSPREAD_CREDENTIALS")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))
    except Exception as e:
        print("❌ 憑證讀取失敗，請確認 Secret 設定:")
        print(traceback.format_exc())
        return None

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df):
    try:
        print(f"🔄 準備寫入分頁 '{sheet_name}'...")
        try:
            wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        except Exception:
            print(f"❌ 嚴重錯誤: 找不到分頁 '{sheet_name}'，請在雲端手動建立！")
            return
            
        if df.empty: return
        
        # 終極型態轉換：避免 numpy float 或 datetime 造成 JSON 解析報錯 (這是之前其他檔案失敗的主因)
        df_clean = df.copy()
        if 'Date' in df_clean.columns and pd.api.types.is_datetime64_any_dtype(df_clean['Date']):
            df_clean['Date'] = df_clean['Date'].dt.strftime("%Y-%m-%d")
        df_clean = df_clean.astype(str).replace({"nan": "", "NaN": "", "NaT": "", "None": ""})
        
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 初次寫入 {len(df_clean)} 筆至 {sheet_name}")
        else:
            existing_dates = set([str(row[0]) for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty:
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 附加 {len(df_new)} 筆新資料至 {sheet_name}")
            else:
                print(f"⚡ {sheet_name} 已是最新")
    except Exception:
        print(f"❌ 寫入 {sheet_name} 異常，詳細報錯:")
        print(traceback.format_exc())

def main():
    print("="*50 + "\n🌍 啟動國際宏觀因子採集\n" + "="*50)
    gc = get_gspread_client()
    if not gc: return
    sp_id = gc.list_spreadsheet_files()[0]['id']
    
    start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    try:
        data = yf.download(list(MACRO_TICKERS.keys()), start=start_date, progress=False)
        # 處理 yfinance 新版 MultiIndex 問題
        if isinstance(data.columns, pd.MultiIndex):
            df_macro = data['Close']
        else:
            df_macro = data
            
        df_macro.rename(columns=MACRO_TICKERS, inplace=True)
        df_macro = df_macro.ffill().dropna(how='all').reset_index()
        df_macro.rename(columns={'index': 'Date', 'Date': 'Date'}, inplace=True)
        
        safe_gspread_write(gc, sp_id, "global_market_factors", df_macro)
    except Exception:
        print("❌ 下載全球因子失敗:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
