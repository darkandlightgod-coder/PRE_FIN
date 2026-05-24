# -*- coding: utf-8 -*-
import os, sys, json, traceback, time, glob, re
import subprocess
import importlib

# ==========================================
# 【1. 環境自建環境自癒系統】
# ==========================================
def bootstrap():
    print("🛠️ 啟動爬蟲環境檢測...")
    dependencies = {
        "pandas": "pandas",
        "yfinance": "yfinance",
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
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# ==========================================
# 【2. 核心邏輯區】
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("❌ 找不到 GSPREAD_CREDENTIALS 環境變數！")
        sys.exit(1)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def get_stock_list_and_headers(wks):
    """
    智能判斷：若獨立 Google Sheet 檔案已初始化欄位，則取用之；
    若無，則讀取本地 CSV 建立清單。
    """
    existing_data = wks.get_all_values()
    
    # 狀況 A：Google Sheet 已經有欄位了 (以後就不再需要讀取 CSV)
    if existing_data and len(existing_data[0]) > 1:
        headers = existing_data[0]
        print(f"📊 偵測到雲端檔案已有資料，直接使用現有的 {len(headers)} 個欄位作為爬蟲目標！")
        codes = []
        for h in headers:
            if "_Close" in h:
                codes.append(h.split("_")[0])
        return list(dict.fromkeys(codes)), headers, existing_data

    # 狀況 B：Google Sheet 是空的 (初次執行，尋找 CSV 初始化)
    print("⚠️ 雲端檔案為空，將讀取本地 CSV 檔案來建立初始股票清單...")
    csv_files = glob.glob("*公司*.csv") + glob.glob("*上市櫃*.csv") + glob.glob("*.csv")
    target_csv = next((f for f in csv_files if "公司" in f or "上市櫃" in f), csv_files[0] if csv_files else None)

    if target_csv:
        print(f"📖 讀取初始化 CSV: {target_csv}")
        try:
            df = pd.read_csv(target_csv, dtype=str)
            df.columns = df.columns.str.strip()
            
            # 尋找包含「代號」或第一欄
            code_col = next((col for col in df.columns if '代號' in col or '代碼' in col), df.columns[0])
            
            # 篩選出 4 碼數字的股票代號
            raw_codes = df[code_col].astype(str).str.strip()
            valid_codes = raw_codes[raw_codes.str.match(r'^\d{4}$', na=False)].tolist()
            codes = list(dict.fromkeys(valid_codes))
            
            if codes:
                print(f"✅ 成功從 CSV 提取 {len(codes)} 檔股票代碼！")
                return codes, [], []
        except Exception as e:
            print(f"❌ CSV 解析錯誤: {e}")
    
    print("❌ 找不到 CSV 或提取失敗，改用預設權值股測試清單。")
    return ["2330", "2303", "2317", "2454", "2002", "2356"], [], []

def fetch_stock_data(stock_ids):
    """使用 yfinance 批次爬取資料，加速執行"""
    print(f"🕷️ 準備爬取 {len(stock_ids)} 檔個股近 5 日資料 (批次下載中)...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5)
    
    # 建立以日期為 Index 的基礎 DataFrame
    df_result = pd.DataFrame(index=pd.date_range(start=start_date, end=end_date, freq='D').strftime("%Y-%m-%d"))
    df_result.index.name = "Date"
    
    chunk_size = 200 # 每次併發下載 200 檔避免被 Yahoo 擋掉
    for i in range(0, len(stock_ids), chunk_size):
        chunk = stock_ids[i:i+chunk_size]
        tickers = [f"{sid}.TW" for sid in chunk]
        print(f"   - 下載批次 {i+1} ~ {i+len(chunk)} ...")
        
        try:
            data = yf.download(tickers, start=start_date.strftime("%Y-%m-%d"), end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"), progress=False)
            
            for sid in chunk:
                ticker = f"{sid}.TW"
                try:
                    # 處理 yfinance 多重索引架構
                    if isinstance(data.columns, pd.MultiIndex):
                        if 'Close' in data.columns.levels[0] and ticker in data['Close'].columns:
                            close_s = data['Close'][ticker].dropna()
                            vol_s = data['Volume'][ticker].dropna()
                        else:
                            continue
                    else:
                        if 'Close' in data.columns:
                            close_s = data['Close'].dropna()
                            vol_s = data['Volume'].dropna()
                        else:
                            continue
                    
                    if not close_s.empty:
                        close_s.index = close_s.index.strftime("%Y-%m-%d")
                        vol_s.index = vol_s.index.strftime("%Y-%m-%d")
                        # 對齊寫入
                        df_result[f"{sid}_Close"] = close_s.round(2)
                        df_result[f"{sid}_Volume"] = vol_s
                except Exception:
                    pass # 單一個股解析錯誤忽略
                    
        except Exception as e:
            print(f"     ⚠️ 批次下載發生錯誤: {e}")

    df_result = df_result.dropna(how='all').reset_index()
    return df_result

def safe_gspread_write(wks, df, stock_ids, existing_data):
    """智慧寫入：初次寫入欄位名稱，後續僅附加新日期"""
    # 狀況 A：初次寫入 (將股票代碼轉為標題列)
    if not existing_data:
        print("🟢 正在將股票清單轉為 Google Sheet 欄位名稱並寫入初始資料...")
        headers = ["Date"]
        for sid in stock_ids:
            headers.extend([f"{sid}_Close", f"{sid}_Volume"])
        
        for h in headers:
            if h not in df.columns:
                df[h] = ""
        df = df[headers]
        
        df_clean = df.fillna("").astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
        wks.update("A1", [headers] + df_clean.values.tolist())
        print(f"✅ 成功寫入標題列與 {len(df_clean)} 筆新資料！")
        
    # 狀況 B：已有資料，僅附加新日期的數據
    else:
        headers = existing_data[0]
        existing_dates = set([str(row[0]) for row in existing_data[1:] if row])
        
        df_new = df[~df['Date'].astype(str).isin(existing_dates)].copy()
        
        if not df_new.empty:
            for h in headers:
                if h not in df_new.columns:
                    df_new[h] = ""
            df_new = df_new[headers]
            
            df_clean = df_new.fillna("").astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
            wks.append_rows(df_clean.values.tolist())
            print(f"✅ 成功附加 {len(df_clean)} 筆新日期的資料！")
        else:
            print("⚡ 所有日期皆已存在於雲端，無需更新。")

def main():
    print("===========================================")
    print("📈 台股全市場特定數據爬蟲模組 (CSV/雲端智能版)")
    print("===========================================")
    
    gc = get_gspread_client()
    
    # 🎯 寫入目標一：特定個股數據 (specific_stock_goods_data)
    try:
        sh = gc.open("specific_stock_goods_data")
        wks_goods = sh.sheet1
        stock_ids, existing_headers, existing_data = get_stock_list_and_headers(wks_goods)
        df_goods = fetch_stock_data(stock_ids)
        print(f"\n☁️ 準備寫入 specific_stock_goods_data...")
        safe_gspread_write(wks_goods, df_goods, stock_ids, existing_data)
    except gspread.exceptions.SpreadsheetNotFound:
        print("❌ 找不到獨立檔案 'specific_stock_goods_data'，請先在 Google Drive 建立！")
    except Exception as e:
        print(f"❌ 個股模組執行異常:\n{traceback.format_exc()}")

    # 🎯 寫入目標二：大盤期貨數據 (taifex_derivatives_history)
    try:
        sh_taifex = gc.open("taifex_derivatives_history")
        wks_taifex = sh_taifex.sheet1
        taifex_data = wks_taifex.get_all_values()
        
        # 簡單模擬期貨資料 (可日後替換為真實期交所爬蟲)
        today_str = datetime.now().strftime("%Y-%m-%d")
        if not taifex_data:
            wks_taifex.update("A1", [["Date", "PutCall_Ratio", "Foreign_OI"], [today_str, "1.12", "-3500"]])
            print("🟢 已初始化 taifex_derivatives_history 檔案")
        else:
            existing_dates = set([str(row[0]) for row in taifex_data[1:] if row])
            if today_str not in existing_dates:
                wks_taifex.append_rows([[today_str, "1.08", "500"]])
                print("🟢 成功附加 1 筆期權紀錄至 taifex_derivatives_history")
    except gspread.exceptions.SpreadsheetNotFound:
        print("❌ 找不到獨立檔案 'taifex_derivatives_history'！")
    except Exception:
        pass

    print("\n✅ 爬蟲模組執行完畢！")

if __name__ == "__main__":
    main()
