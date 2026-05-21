# -*- coding: utf-8 -*-
"""
V10.0 - 模組 1: 全球宏觀因子 (Global Market Factors)
功能: 爬取過去 5 年的全球核心指數 (S&P500, VIX, 費半等)，寫入 global_market_factors。
"""
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os, json, traceback

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json: return None
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def main():
    print("🌍 [模組 1] 啟動 V10.0 全球宏觀因子爬取 (5年歷史)...")
    try:
        factors = {"^GSPC": "SP500", "^VIX": "VIX", "^IXIC": "NASDAQ", "DX=F": "USD_Index", "GC=F": "Gold"}
        df_list = []
        for symbol, name in factors.items():
            print(f"   ➤ 抓取 {name} ({symbol})...")
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5y")
            if not df.empty:
                df = df[['Close']].rename(columns={'Close': name})
                df.index = df.index.tz_localize(None).normalize()
                df_list.append(df)
        
        if df_list:
            df_final = pd.concat(df_list, axis=1).ffill().bfill().reset_index()
            df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
            
            gc = get_gspread_client()
            if gc:
                try:
                    wks = gc.open("global_market_factors").sheet1
                    wks.clear()
                    wks.update([df_final.columns.values.tolist()] + df_final.values.tolist())
                    print("   ✅ 成功寫入 global_market_factors 試算表！")
                except gspread.exceptions.SpreadsheetNotFound:
                    print("   ❌ 找不到 'global_market_factors' 試算表，請在 Google Drive 手動建立空檔案！")
        print("✅ [模組 1] 完成！\n")
    except Exception as e:
        print(f"❌ [模組 1] 發生嚴重錯誤:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
