# -*- coding: utf-8 -*-
"""
V10.1 - 模組 1: 全球宏觀因子 (Global Market Factors) (已更新12:58)
功能: 爬取過去 5 年的全球核心指數，擴充【貴金屬】、【糧食】、【運價】期貨。
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
    print("🌍 [模組 1] 啟動 V10.1 全球宏觀因子爬取 (包含原物料與運價)...")
    try:
        factors = {
            "^GSPC": "SP500", "^VIX": "VIX", "^IXIC": "NASDAQ", "DX=F": "USD_Index", 
            "GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "PA=F": "Palladium", "HG=F": "Copper", 
            "CL=F": "Crude_Oil", "BDRY": "Freight_BDRY", 
            "ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soybean" 
        }
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
            for col in df_final.columns:
                if col != 'Date': df_final[col] = df_final[col].round(4)
            
            gc = get_gspread_client()
            if gc:
                try:
                    wks = gc.open("global_market_factors").sheet1
                    wks.clear()
                    wks.update([df_final.columns.values.tolist()] + df_final.values.tolist())
                    print("   ✅ 成功寫入 global_market_factors 試算表！(包含所有期貨與運價)")
                except gspread.exceptions.SpreadsheetNotFound:
                    print("   ❌ 找不到 'global_market_factors' 試算表！")
        print("✅ [模組 1] 完成！\n")
    except Exception as e:
        print(f"❌ [模組 1] 發生嚴重錯誤:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
