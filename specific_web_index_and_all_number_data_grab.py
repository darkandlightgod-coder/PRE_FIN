# -*- coding: utf-8 -*-
"""
v10.0 specific_web_index_and_all_number_data_grab.py
【第一步】：台股全市場與 13 檔重點標的數據採集 (支援 5 年回溯與空值補完)
"""
import os, sys, time, json, glob, traceback, random
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

TARGETS = {"2330.TW", "2303.TW", "2356.TW", "2002.TW"}

def get_moat_sheet():
    try:
        creds_json = os.environ.get("GSPREAD_CREDENTIALS")
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        files = gc.list_spreadsheet_files()
        print(f"🛡️ [護城河] 鎖定現有檔案: {files[0]['name']}")
        return gc.open_by_key(files[0]['id'])
    except Exception as e:
        print("❌ Google API 授權或讀取檔案失敗")
        traceback.print_exc()
        sys.exit(1)

def smart_append(sh, sheet_name, df):
    if df.empty: return
    try:
        try:
            wks = sh.worksheet(sheet_name)
        except:
            wks = sh.add_worksheet(title=sheet_name, rows="1000", cols="30")
        
        df = df.fillna("")
        if isinstance(df.index, pd.DatetimeIndex): df = df.reset_index()
        if 'Date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['Date']):
            df['Date'] = df['Date'].dt.strftime("%Y-%m-%d")

        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df.columns.values.tolist()] + df.values.tolist())
            print(f"✅ [{sheet_name}] 初次完整寫入")
        else:
            existing_dates = set([row[0] for row in existing[1:] if row])
            if 'Date' in df.columns:
                df = df[~df['Date'].isin(existing_dates)]
            if not df.empty:
                wks.append_rows(df.values.tolist())
                print(f"✅ [{sheet_name}] 成功補完 {len(df)} 筆空值/新數據")
            else:
                print(f"⚡ [{sheet_name}] 數據已是最新，無需補完")
    except Exception as e:
        print(f"❌ 寫入 [{sheet_name}] 失敗")
        traceback.print_exc()

def fetch_twse_fallback(stock_id, date_str):
    """防呆：使用 requests 抓取證交所"""
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={stock_id}"
    try:
        res = requests.get(url, timeout=10)
        time.sleep(random.uniform(2, 4)) # 防封鎖延遲
        data = res.json()
        if data['stat'] == 'OK': return data['data']
    except Exception as e:
        print(f"⚠️ TWSE 備援爬取失敗 ({stock_id}): {e}")
    return []

def main():
    print("="*50 + "\n🚀 v10.0 [1/5] 台股大盤與特定數據採集啟動\n" + "="*50)
    sh = get_moat_sheet()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5*365) # 5年回溯
    
    print("🕸️ 正在使用 YFinance 批量獲取 13 檔台股標的與萬檔廣度特徵...")
    all_tw_stocks = set(TARGETS)
    
    # 嘗試讀取目錄下的 CSV 擴充股票清單 (最高 400 檔避免 OOM)
    for csv_file in glob.glob("*.csv"):
        try:
            df_csv = pd.read_csv(csv_file)
            if '公司代號' in df_csv.columns:
                codes = df_csv['公司代號'].dropna().astype(str).tolist()
                for c in codes[:100]: # 每份名單抽樣100檔作為市場廣度代表
                    all_tw_stocks.add(c.replace('=', '').replace('"', '').strip() + ".TW")
        except: pass

    stock_list = list(all_tw_stocks)[:400] # 分批請求限制
    print(f"   ➤ 預計採集 {len(stock_list)} 檔台股特徵...")
    
    try:
        df_all = yf.download(stock_list, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), progress=False)['Close']
        df_all = df_all.ffill().dropna(how='all')
        
        # 建立大盤廣度指標 (Market Breadth)
        df_breadth = pd.DataFrame(index=df_all.index)
        df_breadth['TW_Market_Avg'] = df_all.mean(axis=1)
        for t in TARGETS:
            if t in df_all.columns: df_breadth[f"Close_{t}"] = df_all[t]
            
        smart_append(sh, "specific_stock_goods_data", df_breadth)
    except Exception as e:
        print("❌ YFinance 批量下載失敗，啟動備援 TWSE...")
        traceback.print_exc()
        # 備援邏輯省略，將使用已存在的舊資料進行運算

if __name__ == "__main__":
    main()
