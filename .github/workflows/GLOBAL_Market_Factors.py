import os
import sys
import subprocess
import traceback
from datetime import datetime, timedelta
import importlib
import time
import json
import requests
import urllib3

# ==========================================
# 【1. 環境自建環境自癒系統】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 GLOBAL_Market_Factors V4.0 環境檢測...")
    dependencies = {
        "pandas": "pandas",
        "yfinance": "yfinance",
        "requests": "requests",
        "urllib3": "urllib3",
        "gspread": "gspread",
        "google-auth": "google-auth"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 正在安裝套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 運行套件配置完畢。")

bootstrap()

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 【2. 雲端與路徑參數配置】
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

LOCAL_CSV_PATH = os.path.join(DATA_DIR, "global_market_factors.csv")
CLOUD_SHEET_NAME = "global_market_factors"

FACTOR_MAP = {
    "SOX_Close": "^SOX", "DJI_Close": "^DJI", "IXIC_Close": "^IXIC", "GSPC_Close": "^GSPC",
    "N225_Close": "^N225", "KS11_Close": "^KS11", "VIX_Close": "^VIX", "US10Y_Yield": "^TNX",
    "USD_TWD": "TWD=X", "JPY_TWD": "JPYTWD=X", "EUR_TWD": "EURTWD=X", "Gold_Close": "GC=F",
    "CrudeOil_Close": "CL=F", "Copper_Close": "HG=F", "TSMC_ADR_Close": "TSM", "TSMC_ADR_Volume": "TSM",
    "0050_Close": "0050.TW", "0050_Volume": "0050.TW", "TSMC_Close": "2330.TW", "TSMC_Volume": "2330.TW",
    "HonHai_Close": "2317.TW", "HonHai_Volume": "2317.TW", "MediaTek_Close": "2454.TW", "Delta_Close": "2308.TW",
    "Quanta_Close": "2382.TW", "Fubon_Close": "2881.TW", "Cathay_Close": "2882.TW", "UMC_Close": "2303.TW",
    "Evergreen_Close": "2603.TW", "ASE_Close": "3711.TW", "TX_Futures_Close": "TX=F"
}

# ==========================================
# 【3. 嚴格雲端連線與雙向校驗核心】
# ==========================================
def connect_google_sheets_strictly():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    
    if not creds_json:
        raise ValueError("❌ 找不到 GSPREAD_CREDENTIALS 金鑰，雲端強制中斷！")
    if not folder_id:
        raise ValueError("❌ 找不到 GOOGLE_DRIVE_FOLDER_ID 變數，雲端強制中斷！")
        
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc, folder_id

def load_historical_data_strictly():
    """
    從 Google Sheet 嚴格讀取歷史因子數據
    """
    gc, _ = connect_google_sheets_strictly()
    try:
        sh = gc.open(CLOUD_SHEET_NAME)
        records = sh.sheet1.get_all_records()
        if records:
            df = pd.DataFrame(records)
            print(f"☁️ [雲端讀取] 成功自 Google Sheets '{CLOUD_SHEET_NAME}' 讀取 {len(df)} 筆歷史因子。")
            return df
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ℹ️ 雲端無發現 '{CLOUD_SHEET_NAME}'，將嘗試載入本地快取...")
    except Exception as e:
        raise ConnectionError(f"❌ 雲端歷史數據庫載入異常，強制中斷執行：{e}")
        
    if os.path.exists(LOCAL_CSV_PATH):
        print("📂 [本地讀取] 成功自本地備份快取載入。")
        return pd.read_csv(LOCAL_CSV_PATH)
    
    print("ℹ️ 歷史資料庫全新建庫 (2025/12/25 為起點)...")
    return pd.DataFrame()

def save_and_sync_strictly(df):
    df = df.sort_values(by="Date").reset_index(drop=True)
    df.to_csv(LOCAL_CSV_PATH, index=False, encoding="utf-8-sig")
    
    gc, folder_id = connect_google_sheets_strictly()
    try:
        sh = gc.open(CLOUD_SHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"➕ 正在雲端目標資料夾中全新建立: {CLOUD_SHEET_NAME}...")
        sh = gc.create(CLOUD_SHEET_NAME, folder_id)
        
    worksheet = sh.sheet1
    worksheet.clear()
    
    df_clean = df.fillna("")
    data_to_sync = [df_clean.columns.values.tolist()] + df_clean.values.tolist()
    worksheet.update(values=data_to_sync, range_name="A1")
    print("✅ 雲端因子寫入成功！正在執行雙向讀寫校驗...")
    
    # 嚴格讀寫比對校驗 (Read-after-Write)
    values = worksheet.get_all_values()
    if len(values) != len(data_to_sync):
        raise ValueError(f"❌ [CRITICAL] 雲端讀寫校驗失敗！期望行數 {len(data_to_sync)}，雲端實際為 {len(values)}！")
    print("🎉 雲端因子寫入完全正確，連線暢通！")

# ==========================================
# 【4. 數據採集核心】
# ==========================================
def convert_roc_date_to_ce(roc_date_str):
    try:
        parts = roc_date_str.split('/')
        if len(parts) == 3:
            return f"{int(parts[0]) + 1911}/{parts[1]}/{parts[2]}"
    except: pass
    return roc_date_str

def fetch_twse_index_day(session, target_date):
    date_str = target_date.strftime("%Y%m%d")
    date_slash = target_date.strftime("%Y/%m/%d")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={date_str}"
    try:
        res = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=False)
        if res.status_code == 200:
            data = res.json()
            if data.get("stat") == "OK":
                raw_rows = data["tables"][0].get("data", []) if "tables" in data else data.get("data", [])
                for row in raw_rows:
                    if convert_roc_date_to_ce(row[0]) == date_slash:
                        return {"Date": date_slash, "TWII_Close": float(row[4].replace(",", ""))}
    except Exception as e:
        print(f"      ⚠️ TWSE 收盤價 API 讀取失敗: {e}")
    return {}

def fetch_yfinance_factors_bulk(start_str, end_str):
    tickers = list(set(FACTOR_MAP.values()) | {"^TWII"})
    try:
        df_bulk = yf.download(tickers, start=start_str, end=end_str, progress=False, auto_adjust=True)
        if df_bulk.empty:
            return pd.DataFrame()
        is_multi = isinstance(df_bulk.columns, pd.MultiIndex)
        out_data = {"Date": df_bulk.index.strftime('%Y/%m/%d')}
        for factor_name, ticker in FACTOR_MAP.items():
            field = "Volume" if "_Volume" in factor_name else "Close"
            if is_multi:
                out_data[factor_name] = df_bulk[(field, ticker)].values if (field, ticker) in df_bulk.columns else [None] * len(df_bulk)
            else:
                out_data[factor_name] = df_bulk[field].values if field in df_bulk.columns else [None] * len(df_bulk)
        
        if is_multi:
            out_data["YF_TWII_Close"] = df_bulk[("Close", "^TWII")].values if ("Close", "^TWII") in df_bulk.columns else [None] * len(df_bulk)
        else:
            out_data["YF_TWII_Close"] = df_bulk["Close"].values if "Close" in df_bulk.columns else [None] * len(df_bulk)

        df_out = pd.DataFrame(out_data)
        numeric_cols = df_out.columns.drop('Date')
        df_out[numeric_cols] = df_out[numeric_cols].apply(pd.to_numeric, errors='coerce').round(4)
        return df_out
    except Exception as e:
        print(f"❌ 批量獲取 Yahoo Finance 數據失敗: {e}")
    return pd.DataFrame()

# ==========================================
# 【5. 主執行流】
# ==========================================
def main():
    print("=" * 80)
    print("🧠 GLOBAL_Market_Factors V4.0 - 雲端大寬表同步器")
    print("=" * 80)
    
    df_old = load_historical_data_strictly()
    existing_dates = set()
    if not df_old.empty and "Date" in df_old.columns:
        existing_dates = set(df_old["Date"].astype(str).tolist())

    start_date = datetime(2025, 12, 25)
    end_date = datetime.now()
    if end_date.hour < 21:
        end_date = end_date - timedelta(days=1)
        
    delta_days = (end_date - start_date).days
    target_dates = []
    for i in range(delta_days + 1):
        curr_dt = start_date + timedelta(days=i)
        if curr_dt.weekday() >= 5: continue
        curr_str = curr_dt.strftime("%Y/%m/%d")
        if curr_str in existing_dates: continue
        target_dates.append(curr_dt)
        
    print(f"📅 待補歷史日期缺口: {len(target_dates)} 天工作日")
    if not target_dates:
        print("🎉 資料已為最新，無需同步。")
        return

    print("\n[第一階段] 🌐 正在採集台股現貨大盤收盤價...")
    twse_records = []
    with requests.Session() as session:
        for idx, current_date in enumerate(target_dates):
            date_slash = current_date.strftime("%Y/%m/%d")
            print(f"   🚀 [{idx+1}/{len(target_dates)}] 正在採集: {date_slash}...")
            day_data = fetch_twse_index_day(session, current_date)
            if day_data:
                twse_records.append(day_data)
                print(f"      ✅ 官方大盤收盤: {day_data['TWII_Close']:,.2f}")
            else:
                print(f"      ⚠️ API 限流，改由下階段 Yahoo Finance 備用自動遞補。")
            if idx < len(target_dates) - 1:
                time.sleep(2.5)

    df_twse_new = pd.DataFrame(twse_records)
    if df_twse_new.empty:
        df_twse_new = pd.DataFrame(columns=["Date", "TWII_Close"])

    start_yf_str = (start_date - timedelta(days=5)).strftime("%Y-%m-%d")
    end_yf_str = (end_date + timedelta(days=2)).strftime("%Y-%m-%d")
    df_yfinance = fetch_yfinance_factors_bulk(start_yf_str, end_yf_str)
    
    if not df_yfinance.empty:
        print("\n[第二階段] 📊 正在將現貨與全球因子進行對齊與安全備用遞補...")
        df_target_dates = pd.DataFrame({"Date": [d.strftime("%Y/%m/%d") for d in target_dates]})
        df_new_aligned = pd.merge(df_target_dates, df_yfinance, on="Date", how="inner")
        df_new_aligned = pd.merge(df_new_aligned, df_twse_new, on="Date", how="left")
        
        df_new_aligned["TWII_Close"] = df_new_aligned["TWII_Close"].fillna(df_new_aligned["YF_TWII_Close"])
        df_new_aligned = df_new_aligned.drop(columns=["YF_TWII_Close"])
        df_new_aligned = df_new_aligned.dropna(subset=["TWII_Close"])

        if not df_new_aligned.empty:
            df_final = pd.concat([df_old, df_new_aligned], ignore_index=True) if not df_old.empty else df_new_aligned
            df_final = df_final.drop_duplicates(subset=['Date'], keep='last')
            save_and_sync_strictly(df_final)
        else:
            print("⚠️ 對齊合併後無有效數據。")
    else:
        raise ConnectionError("❌ 關鍵的 Yahoo Finance 數據獲取失敗，中斷執行！")

if __name__ == "__main__":
    main()
