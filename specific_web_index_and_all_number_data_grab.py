# -*- coding: utf-8 -*-
"""
V18 終極無頭融合版 (純 Requests 極速期交所爬蟲 + 動態欄位引擎 + YF 整合)
特色：
1. 捨棄 Playwright：極速 requests 請求，不怕超時卡死。
2. 動態欄位解析引擎：自動識別期交所表格商品(大台、小台、選擇權等)與法人(外資、投信等)，
   自動對齊並生成您 CSV 上的數百個欄位，免手動維護對應表！
3. 智慧日期尋找：遇到假日或無交易日，自動往前推算直到有數據為止。
4. Google Drive ID 支援：如果表單不存在，會自動建立於指定資料夾。
"""
import os
import json
import pandas as pd
import numpy as np
import gspread
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
PERIOD = "1mo" # YF 抓取範圍
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ==========================================
# 區塊 A: TAIFEX 期交所輕量極速爬蟲 (動態解析引擎)
# ==========================================

# 商品名稱對應前綴字典
PRODUCT_MAP = {
    '臺股期貨': 'TX', '小型臺指期貨': 'MTX', '微型臺指期貨': 'TMF', 
    '電子期貨': 'TE', '金融期貨': 'TF', '臺指選擇權': 'TXO', 
    '股票期貨': 'STF', '股票選擇權': 'STO', '半導體30期貨': 'SOF',
    '航運期貨': 'SHF', '台灣生技期貨': 'BTF', '客製化小型臺指期貨': 'MXP'
}

# 法人名稱對應字典
IDENTITY_MAP = {'自營商': 'Dealer', '投信': 'Trust', '外資及陸資': 'Foreign'}

# 12個特徵欄位後綴 (按照期交所表格由左至右順序)
METRICS_SUFFIX = [
    'Trade_Long_Vol', 'Trade_Long_Val', 'Trade_Short_Vol', 'Trade_Short_Val', 'Trade_Net_Vol', 'Trade_Net_Val',
    'OI_Long_Vol', 'OI_Long_Val', 'OI_Short_Vol', 'OI_Short_Val', 'OI_Net_Vol', 'OI_Net_Val'
]

def parse_taifex_institutional_table(html, data_dict):
    """動態解析期交所【三大法人】表格，自動生成欄位名並存入 dict"""
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='table_f')
    if not table: return False
    
    has_data = False
    current_product_prefix = None
    
    for tr in table.find_all('tr'):
        tds = tr.find_all(['td', 'th'])
        texts = [td.text.strip().replace(',', '') for td in tds]
        
        # 1. 偵測當前列屬於哪個商品 (處理 rowspan 的影響)
        for t in texts:
            for ch_name, prefix in PRODUCT_MAP.items():
                if ch_name in t:
                    current_product_prefix = prefix
                    break
                    
        # 2. 偵測當前列屬於哪個法人，並提取後面 12 個數據
        if current_product_prefix:
            for idx, t in enumerate(texts):
                if t in IDENTITY_MAP:
                    identity = IDENTITY_MAP[t]
                    # 法人名稱後面的 12 個格子就是我們要的數據
                    values = texts[idx+1 : idx+13]
                    if len(values) == 12:
                        has_data = True
                        for metric, val in zip(METRICS_SUFFIX, values):
                            col_name = f"{current_product_prefix}_{identity}_{metric}"
                            data_dict[col_name] = val
                    break
    return has_data

def scrape_taifex_target_date(target_date):
    """對特定日期發起爬蟲，回傳爬到的數據字典"""
    date_str_slash = target_date.strftime('%Y/%m/%d')
    today_data = {}
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print(f"   🔎 嘗試向期交所索取 {date_str_slash} 數據...")

    # 1. 抓取 Put/Call Ratio
    try:
        url_pc = "https://www.taifex.com.tw/cht/3/pcRatio"
        res_pc = session.post(url_pc, data={"queryStartDate": date_str_slash, "queryEndDate": date_str_slash}, timeout=10)
        soup_pc = BeautifulSoup(res_pc.text, 'html.parser')
        table_pc = soup_pc.find('table', class_='table_f')
        if table_pc and len(table_pc.find_all('tr')) > 1:
            cols = table_pc.find_all('tr')[1].find_all('td')
            if len(cols) >= 6:
                today_data['TAIFEX_Put_Volume'] = cols[1].text.replace(',', '').strip()
                today_data['TAIFEX_Call_Volume'] = cols[2].text.replace(',', '').strip()
                today_data['TAIFEX_PC_Ratio_Volume'] = cols[3].text.replace(',', '').strip()
                today_data['TAIFEX_Put_OI'] = cols[4].text.replace(',', '').strip()
                today_data['TAIFEX_Call_OI'] = cols[5].text.replace(',', '').strip()
                today_data['TAIFEX_PC_Ratio_OI'] = cols[6].text.replace(',', '').strip()
    except Exception:
        pass

    # 2. 抓取 三大法人-期貨
    try:
        url_fut = "https://www.taifex.com.tw/cht/3/futContractsDate"
        res_fut = session.post(url_fut, data={"queryDate": date_str_slash}, timeout=10)
        parse_taifex_institutional_table(res_fut.text, today_data)
    except Exception:
        pass

    # 3. 抓取 三大法人-選擇權
    try:
        url_opt = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
        res_opt = session.post(url_opt, data={"queryDate": date_str_slash}, timeout=10)
        parse_taifex_institutional_table(res_opt.text, today_data)
    except Exception:
        pass

    return today_data

def get_taifex_latest_data():
    """智慧尋找最新交易日，並組合成 DataFrame"""
    today = datetime.now()
    if today.hour < 15: # 確保下午 3 點盤後數據已產出
        today -= timedelta(days=1)
        
    print("🌐 [Requests 極速引擎] 啟動期交所數據挖掘...")
    
    # 往前找尋有資料的最近一天 (最多找 7 天)
    for i in range(7):
        target_date = today - timedelta(days=i)
        # 遇到假日略過 (0=週一, 5=週六, 6=週日)
        if target_date.weekday() >= 5: continue 
        
        data = scrape_taifex_target_date(target_date)
        
        # 只要有抓到一筆資料(大於0)，代表這天有交易，結束尋找
        if len(data) > 0:
            print(f"   ✅ 成功獲取 {target_date.strftime('%Y-%m-%d')} 共 {len(data)} 個數據維度！")
            target_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            df = pd.DataFrame([data], index=[target_date])
            df.index.name = 'Date'
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
            
    print("   ❌ 過去 7 天都找不到交易資料，返回空表。")
    return pd.DataFrame()

# ==========================================
# 區塊 B: Yahoo Finance 爬蟲
# ==========================================
def get_tickers_mapping(headers):
    mapping = {}
    for header in headers:
        if header.endswith("_Close"):
            base_name = header.replace("_Close", "")
            if base_name.isdigit():
                mapping[base_name] = f"{base_name}.TW"
            else:
                mapping[base_name] = base_name
    return mapping

def fetch_and_flatten_yf_data(ticker_map, period):
    print("📡 [YF 股票引擎] 啟動全球與台股報價抓取...")
    yf_tickers = list(ticker_map.values())
    if not yf_tickers: return pd.DataFrame()
    
    rev_map = {v: k for k, v in ticker_map.items()}
    df = yf.download(yf_tickers, period=period, threads=True, progress=False)
    
    if df.empty: return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        flat_cols = []
        valid_cols = []
        for col in df.columns:
            metric = col[0]
            ticker = col[1]
            if metric in ['Close', 'Volume']:
                header_prefix = rev_map.get(ticker, ticker)
                flat_cols.append(f"{header_prefix}_{metric}")
                valid_cols.append(col)
        df = df[valid_cols]
        df.columns = flat_cols
    else:
        df = df[['Close', 'Volume']]
        header_prefix = rev_map.get(yf_tickers[0], yf_tickers[0])
        df.columns = [f"{header_prefix}_Close", f"{header_prefix}_Volume"]

    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

# ==========================================
# 區塊 C: 主程式與矩陣融合 (含 Drive ID 支援)
# ==========================================
def main():
    print("="*60)
    print("⚡ 啟動 V18 終極無頭融合版 (自動欄位引擎)")
    print("="*60)

    # 1. 初始化 Google 驗證
    print("☁️ 連接 Google Workspace...")
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    
    if not creds_json:
        print("❌ 致命錯誤：找不到 GSPREAD_CREDENTIALS 機密。")
        return
        
    credentials = Credentials.from_service_account_info(
        json.loads(creds_json), 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(credentials)
    
    # 2. 開啟或建立表單
    try:
        worksheet = gc.open(SHEET_NAME).sheet1
        print(f"   ✅ 成功開啟既有表單 [{SHEET_NAME}]")
    except gspread.SpreadsheetNotFound:
        print(f"   ⚠️ 找不到 [{SHEET_NAME}]，正在自動建立新表單...")
        if folder_id:
            sh = gc.create(SHEET_NAME, folder_id=folder_id)
            print(f"   📁 已建立至指定資料夾 (ID: {folder_id})")
        else:
            sh = gc.create(SHEET_NAME)
            print("   📁 已建立至 Google Drive 根目錄 (因為未找到 Folder ID)")
        worksheet = sh.sheet1
    
    # 3. 讀取舊資料
    all_values = worksheet.get_all_values()
    headers = [str(h).strip() for h in all_values[0]] if all_values else []
    df_cloud = pd.DataFrame(all_values[1:], columns=headers) if len(all_values) > 1 else pd.DataFrame()
    
    if not df_cloud.empty:
        df_cloud['Date'] = pd.to_datetime(df_cloud['Date'], errors='coerce')
        df_cloud.dropna(subset=['Date'], inplace=True)
        df_cloud.set_index('Date', inplace=True)
        df_cloud = df_cloud.replace(r'^\s*$', np.nan, regex=True)
        for col in df_cloud.columns:
            if col.endswith(("_Close", "_Volume", "_Vol", "_Val", "_OI")):
                df_cloud[col] = pd.to_numeric(df_cloud[col], errors='coerce')

    # 4. 取得 TAIFEX 與 YF 新數據
    df_taifex = get_taifex_latest_data()
    ticker_map = get_tickers_mapping(headers)
    df_yf = fetch_and_flatten_yf_data(ticker_map, PERIOD)
    
    # 5. 數據矩陣融合
    print("\n🧠 啟動 Pandas 數據矩陣融合...")
    if not df_taifex.empty and not df_yf.empty:
        df_new = df_yf.combine_first(df_taifex)
    elif not df_taifex.empty:
        df_new = df_taifex
    elif not df_yf.empty:
        df_new = df_yf
    else:
        df_new = pd.DataFrame()

    if df_new.empty:
        print("沒有抓到任何新資料。")
        return

    # 合併新舊資料
    if not df_cloud.empty:
        df_final = df_new.combine_first(df_cloud)
    else:
        df_final = df_new.copy()

    df_final = df_final[df_final.index.notna()]
    df_final.sort_index(inplace=True)

    # 6. 寫回 Google Sheet
    print("🔄 整包覆蓋寫回 Google Sheet...")
    df_final.reset_index(inplace=True)
    df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
    
    # 對齊欄位：如果雲端本來有 header，維持順序；爬到新的特徵就加在後面
    if headers and 'Date' in headers:
        ordered_cols = ['Date'] + [col for col in headers if col in df_final.columns and col != 'Date']
        new_cols = [col for col in df_final.columns if col not in ordered_cols]
        df_final = df_final[ordered_cols + new_cols]
    
    df_final = df_final.fillna("")
    output_data = [df_final.columns.tolist()] + df_final.values.tolist()
    
    worksheet.clear()
    worksheet.update(values=output_data, range_name=None)
    print(f"🎉 成功寫入！目前雲端資料庫累積 {len(df_final)} 天數據，共 {len(df_final.columns)} 個特徵欄位！")

if __name__ == "__main__":
    main()
