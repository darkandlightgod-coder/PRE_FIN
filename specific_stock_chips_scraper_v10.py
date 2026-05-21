# -*- coding: utf-8 -*-
"""
V10.1 - 模組 4: 13檔指定個股與全台單價 RawData (已更新12:58)
功能: 完美讀取 CSV 名單，以 400 筆為單位批次抓取全台單價與 13 檔指標，遇到封鎖自動備份寫入 specific_stock_goods_data。
"""
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os, json, traceback, time

TARGETS = ["^TWII", "2330.TW", "2303.TW", "2356.TW", "2002.TW", "NVDA", "TSLA", "INTC", "AAPL", "MSFT", "AMZN", "LLY", "NVO", "7203.T"]

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json: return None
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def get_csv_tickers():
    """全面解析所有提供的 CSV 檔案，獲取真實台股清單"""
    files = ["所有上市公司.csv", "所有上櫃公司.csv", "所有興櫃公司.csv", "所有公開發行公司.csv", "所有創櫃公司.csv"]
    tickers = set(TARGETS)
    for f in files:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f, dtype=str)
                if "公司代號" in df.columns:
                    for code in df["公司代號"].dropna():
                        code_str = str(code).strip()
                        if code_str.isdigit() and len(code_str) >= 4:
                            tickers.add(f"{code_str}.TW")
            except: pass
    return list(tickers)

def main():
    print("🕵️ [模組 4] 啟動 V10.1 全台個股單價與核心大盤採集...")
    try:
        tickers = get_csv_tickers()
        print(f"   ➤ 從 CSV 成功解析出 {len(tickers)} 檔股票。準備以 400 筆為批次進行 5 年資料抓取...")
        
        df_list = []
        batch_size = 400
        for i in range(0, len(tickers), batch_size):
            chunk = tickers[i:i+batch_size]
            print(f"   ➤ 正在下載批次 {i//batch_size + 1} ({len(chunk)} 檔)...")
            try:
                data = yf.download(chunk, period="5y", group_by="ticker", progress=False, threads=True)
                for t in chunk:
                    if len(chunk) == 1:
                        if 'Close' in data: df_list.append(data['Close'].rename(t))
                    else:
                        if t in data and 'Close' in data[t]:
                            s = data[t]['Close'].dropna()
                            if not s.empty: df_list.append(s.rename(t))
            except Exception as e:
                print(f"   ⚠️ 遭到 API 封鎖限制，觸發斷點保護，保留已抓取資料！(錯誤: {e})")
                break # 直接中斷迴圈，將前面抓到的 df_list 保留
            time.sleep(1.5)
        
        if df_list:
            df_final = pd.concat(df_list, axis=1).ffill().fillna(0).reset_index()
            df_final['Date'] = pd.to_datetime(df_final['Date']).dt.strftime('%Y-%m-%d')
            # 轉換小數點防記憶體超載
            for col in df_final.columns:
                if col != 'Date': df_final[col] = df_final[col].round(2)
            
            gc = get_gspread_client()
            if gc:
                try:
                    wks = gc.open("specific_stock_goods_data").sheet1
                    wks.clear()
                    wks.update([df_final.columns.values.tolist()] + df_final.astype(str).values.tolist())
                    print(f"   ✅ 成功寫入 {len(df_final.columns)-1} 檔股票歷史單價至 specific_stock_goods_data！")
                except gspread.exceptions.SpreadsheetNotFound:
                    print("   ❌ 找不到 'specific_stock_goods_data' 試算表，請手動建立！")
        
        print("✅ [模組 4] 完成！\n")
    except Exception as e:
        print(f"❌ [模組 4] 發生嚴重錯誤:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
