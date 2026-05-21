# -*- coding: utf-8 -*-
"""
V10.1 - 模組 4: 13檔指定個股與大盤 歷史 RawData (specific_stock_goods_data) (已更新12:58)
功能: 真實抓取 14 檔標的 5 年全量歷史開高低收與量能，整合並寫入 Google Sheet。
"""
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os, json, traceback

TARGETS = ["^TWII", "2330.TW", "2303.TW", "2356.TW", "2002.TW", "NVDA", "TSLA", "INTC", "AAPL", "MSFT", "AMZN", "LLY", "NVO", "7203.T"]

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json: return None
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def main():
    print("🕵️ [模組 4] 啟動 V10.1 核心個股與大盤 RawData 全歷史採集...")
    try:
        print(f"   ➤ 正在從 Yahoo Finance 批次拉取 5 年歷史資料...")
        df_yf = yf.download(TARGETS, period="5y", group_by="ticker", progress=False)
        
        merged_data = []
        for sym in TARGETS:
            if sym in df_yf:
                # 擷取單一股票的 OHLCV
                df_sym = df_yf[sym].dropna(subset=['Close']).copy()
                if not df_sym.empty:
                    df_sym = df_sym.reset_index()
                    df_sym['Symbol'] = sym
                    merged_data.append(df_sym[['Date', 'Symbol', 'Open', 'High', 'Low', 'Close', 'Volume']])
        
        if merged_data:
            df_final = pd.concat(merged_data, ignore_index=True)
            df_final['Date'] = pd.to_datetime(df_final['Date']).dt.strftime('%Y-%m-%d')
            # 將 Close 轉為小數第二位，減少體積
            df_final[['Open', 'High', 'Low', 'Close']] = df_final[['Open', 'High', 'Low', 'Close']].round(2)
            df_final = df_final.sort_values(by=['Date', 'Symbol']).reset_index(drop=True)
            
            gc = get_gspread_client()
            if gc:
                try:
                    wks = gc.open("specific_stock_goods_data").sheet1
                    wks.clear()
                    # 因為資料可能高達數萬筆，改以較安全的方式寫入
                    wks.update([df_final.columns.values.tolist()] + df_final.astype(str).values.tolist())
                    print(f"   ✅ 成功寫入 {len(df_final)} 筆歷史 RawData 至 specific_stock_goods_data 試算表！")
                except gspread.exceptions.SpreadsheetNotFound:
                    print("   ❌ 找不到 'specific_stock_goods_data' 試算表，請手動建立！")
        
        print("✅ [模組 4] 完成！\n")
    except Exception as e:
        print(f"❌ [模組 4] 發生嚴重錯誤:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
