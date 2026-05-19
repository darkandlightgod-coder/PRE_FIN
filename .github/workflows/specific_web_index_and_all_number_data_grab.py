import os
import sys
import subprocess
import traceback
from datetime import datetime, timedelta
import importlib
import time
import re
import json
import random

# ==========================================
# 【1. 雲端自癒與自動化瀏覽器配置】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 specific_web_index_and_all_number_data_grab V4.0 環境自檢...")
    dependencies = {
        "pandas": "pandas",
        "beautifulsoup4": "bs4",
        "playwright": "playwright",
        "gspread": "gspread",
        "oauth2client": "oauth2client"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 正在自動安裝運作必要套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 雲端運作路徑配置完畢。")

    try:
        from playwright.sync_api import sync_playwright
        print("🌐 檢查 Playwright 瀏覽器核心 (Chromium)...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True)
    except Exception as e:
        print(f"⚠️ 瀏覽器核心檢索提醒: {e}")

bootstrap()

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 【2. 動態路徑與雲端設定對齊】
# ==========================================
BASE_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(BASE_DIR, exist_ok=True)
LOCAL_CSV_PATH = os.path.join(BASE_DIR, "taifex_derivatives_history.csv")

CLOUD_SHEET_NAME = "taifex_derivatives_history"
HEADLESS_MODE = True

COMMODITY_MAP = {
    "臺股期貨": "TX", "台股期貨": "TX", "小型臺指": "MTX", "小型台指": "MTX",
    "電子期貨": "TE", "金融期貨": "TF", "臺灣半導體": "SOF", "半導體30": "SOF",
    "臺灣永續": "E4F", "永續期貨": "E4F", "臺灣生技": "BTF", "生技期貨": "BTF",
    "臺灣航運": "SHF", "航運期貨": "SHF", "櫃買": "GTF", "非金電": "XIF",
    "富時臺灣": "FTF", "美國道瓊": "UDF", "美國標普": "SPF", "美國那斯達克": "UNF",
    "美國費城半導體": "SXF", "英國富時": "F1F", "東證": "TJF", "黃金期貨": "GDF",
    "臺幣黃金": "TGF", "布蘭特原油": "BRF", "歐元兌美元": "XEF", "美元兌日圓": "XJF",
    "澳幣兌美元": "XAF", "英鎊兌美元": "XBF", "人民幣兌美元": "XCF", "美元兌人民幣": "RHF",
    "股票期貨": "STF", "ETF期貨": "ETF"
}

# ==========================================
# 【3. 雲端 Google Sheets 雙向讀寫核心模組】
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope))
        except Exception as e:
            print(f"⚠️ 解析 GSPREAD_CREDENTIALS 失敗: {e}")
            
    local_creds = "credentials.json"
    if os.path.exists(local_creds):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name(local_creds, scope))
        except: pass
    return None

def load_historical_taifex():
    gc = get_gspread_client()
    if gc:
        try:
            sh = gc.open(CLOUD_SHEET_NAME)
            records = sh.sheet1.get_all_records()
            if records:
                df = pd.DataFrame(records)
                print(f"☁️ [雲端載入] 成功自 Google Sheets 讀取 {len(df)} 筆期權數據。")
                return df
        except Exception as e:
            print(f"⚠️ 雲端期權數據讀取失敗 (將由本地遞補): {e}")
            
    if os.path.exists(LOCAL_CSV_PATH):
        print(f"📂 [本地載入] 讀取本地期權數據歷史備份: {LOCAL_CSV_PATH}")
        return pd.read_csv(LOCAL_CSV_PATH)
    return pd.DataFrame()

def save_and_sync_taifex(df):
    df = df.sort_values(by="Date").reset_index(drop=True)
    df.to_csv(LOCAL_CSV_PATH, index=False, encoding="utf-8-sig")
    
    gc = get_gspread_client()
    if gc:
        try:
            try:
                sh = gc.open(CLOUD_SHEET_NAME)
            except gspread.exceptions.SpreadsheetNotFound:
                sh = gc.create(CLOUD_SHEET_NAME)
            sheet = sh.sheet1
            sheet.clear()
            df_clean = df.fillna("")
            sheet.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
            print(f"🎉 [雲端同步] 成功更新 Google Sheets '{CLOUD_SHEET_NAME}'，共 {len(df_clean)} 筆。")
        except Exception as e:
            print(f"❌ 雲端期權同步失敗: {e}")

# ==========================================
# 【4. 爬蟲解析引擎】
# ==========================================
def get_latest_completed_trading_date():
    now = datetime.now()
    test_date = now
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        test_date = now - timedelta(days=1)
    while test_date.weekday() >= 5:
        test_date = test_date - timedelta(days=1)
    return test_date

def normalize_date(d_str):
    try:
        d_str = d_str.strip().replace('-', '/')
        parts = d_str.split('/')
        if len(parts) == 3:
            return f"{int(parts[0])}/{int(parts[1])}/{int(parts[2])}"
    except: pass
    return d_str

def clean_int(val_str):
    if not val_str: return 0
    val_str = val_str.strip().replace(",", "").replace("%", "")
    if val_str in ["", "-", "—", "None", "查無資料"]: return 0
    val_str = re.sub(r'[^\d\-]', '', val_str)
    try: return int(val_str)
    except: return 0

def get_commodity_code(name):
    name = name.strip()
    if name in ["自營商", "投信", "外資", "外資及陸資", "合計", "身份別"]: return "IGNORE"
    for key, code in COMMODITY_MAP.items():
        if key in name: return code
    return "IGNORE"

def fetch_pc_ratio_day(context, target_date):
    date_str = target_date.strftime("%Y/%m/%d")
    url = f"https://www.taifex.com.tw/cht/3/pcRatio?queryStartDate={date_str}&queryEndDate={date_str}"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        target_table = None
        for table in soup.find_all('table'):
            if "買賣權未平倉量" in table.get_text():
                target_table = table
                break
        if not target_table: return {}
        norm_target_date = normalize_date(date_str)
        for row in target_table.find_all('tr'):
            tds = row.find_all('td')
            if len(tds) >= 7:
                if normalize_date(tds[0].get_text()) == norm_target_date:
                    return {
                        "TAIFEX_Put_Volume": float(tds[1].get_text().replace(",", "").strip()),
                        "TAIFEX_Call_Volume": float(tds[2].get_text().replace(",", "").strip()),
                        "TAIFEX_PC_Ratio_Volume": float(tds[3].get_text().replace(",", "").replace("%", "").strip()),
                        "TAIFEX_Put_OI": float(tds[4].get_text().replace(",", "").strip()),
                        "TAIFEX_Call_OI": float(tds[5].get_text().replace(",", "").strip()),
                        "TAIFEX_PC_Ratio_OI": float(tds[6].get_text().replace(",", "").replace("%", "").strip())
                    }
    except: pass
    finally: page.close()
    return {}

def fetch_futures_day(context, target_date):
    date_str = target_date.strftime("%Y/%m/%d")
    url = f"https://www.taifex.com.tw/cht/3/futContractsDate?queryType=1&queryDate={date_str}"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        if "查無資料" in soup.get_text() or "沒有資料" in soup.get_text():
            return {}
            
        results = {}
        current_commodity = None
        col_suffixes = [
            "Trade_Long_Vol", "Trade_Long_Val", "Trade_Short_Vol", "Trade_Short_Val",
            "Trade_Net_Vol", "Trade_Net_Val", "OI_Long_Vol", "OI_Long_Val",
            "OI_Short_Vol", "OI_Short_Val", "OI_Net_Vol", "OI_Net_Val"
        ]
        
        for row in soup.find_all('tr'):
            td_cells = row.find_all(['td', 'th'])
            if len(td_cells) < 10: continue
            cells = [td.get_text().strip() for td in td_cells]
            
            identity_idx, identity = -1, None
            for idx, cell in enumerate(cells):
                if "自營商" in cell: identity, identity_idx = "Dealer", idx
                elif "投信" in cell: identity, identity_idx = "Trust", idx
                elif "外資" in cell: identity, identity_idx = "Foreign", idx
            
            if identity is None or identity_idx < 0: continue
            if identity_idx > 0:
                temp_code = get_commodity_code(cells[identity_idx - 1])
                if temp_code != "IGNORE": current_commodity = temp_code
            
            if not current_commodity or current_commodity == "IGNORE": continue
            data_cells = cells[identity_idx + 1:]
            if len(data_cells) < 12: continue
            
            prefix = f"{current_commodity}_{identity}"
            for idx, suffix in enumerate(col_suffixes):
                results[f"{prefix}_{suffix}"] = clean_int(data_cells[idx])

        try:
            mtx_foreign = results.get("MTX_Foreign_OI_Net_Vol", 0)
            mtx_trust = results.get("MTX_Trust_OI_Net_Vol", 0)
            mtx_dealer = results.get("MTX_Dealer_OI_Net_Vol", 0)
            results["MTX_Retail_Net_OI"] = -(mtx_foreign + mtx_trust + mtx_dealer)
        except: pass
        return results
    except: return {}
    finally: page.close()

# ==========================================
# 【5. 核心增量對齊控制流】
# ==========================================
def main():
    print("=" * 80)
    print("🧠 期權高維特徵增量同步器 V4.0 (線上化自適應版)")
    print("=" * 80)
    
    df_old = load_historical_taifex()
    existing_dates = set()
    if not df_old.empty and "Date" in df_old.columns:
        existing_dates = set(df_old["Date"].astype(str).tolist())

    start_date = datetime(2026, 1, 2)
    end_date = get_latest_completed_trading_date()
    delta_days = (end_date - start_date).days
    target_dates = []
    
    for i in range(delta_days + 1):
        curr_dt = start_date + timedelta(days=i)
        if curr_dt.weekday() >= 5: continue
        curr_str = curr_dt.strftime("%Y/%m/%d")
        if curr_str in existing_dates: continue
        target_dates.append(curr_dt)

    print(f"🔍 待補齊期權缺口天數: {len(target_dates)} 天工作日")
    if not target_dates:
        print("🎉 [最新狀態] 本地與雲端期權歷史數據皆已同步，無須更新。")
        print("=" * 80)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS_MODE)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        new_records = []
        for idx, current_date in enumerate(target_dates):
            today_str = current_date.strftime("%Y/%m/%d")
            print(f"🚀 [{idx+1}/{len(target_dates)}] 正在同步: {today_str}...")
            
            pc_data = fetch_pc_ratio_day(context, current_date)
            time.sleep(1.0)
            futures_data = fetch_futures_day(context, current_date)
            
            if not pc_data or not futures_data:
                print(f"   ⚠️ 該交易日查無期權市場資訊，自動跳過。")
                continue
            
            day_record = {"Date": today_str}
            day_record.update(pc_data)
            day_record.update(futures_data)
            new_records.append(day_record)
            
            if idx < len(target_dates) - 1:
                time.sleep(random.uniform(2.5, 4.0))
                
        if new_records:
            df_new = pd.DataFrame(new_records)
            df_final = pd.concat([df_old, df_new], ignore_index=True) if not df_old.empty else df_new
            df_final = df_final.drop_duplicates(subset=["Date"], keep="last")
            save_and_sync_taifex(df_final)
            
        browser.close()

if __name__ == "__main__":
    main()
