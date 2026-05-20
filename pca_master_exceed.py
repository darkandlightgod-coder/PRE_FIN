# -*- coding: utf-8 -*-
"""
V14.1 PCA_Master_Exceed 巨量全市場融合 (解除封印極速版) & 雲端護城河
=========================================================
1. 【Drive API 護城河】: 零消耗覆寫，防 403 報錯。
2. 【最終戰報注入】: 鎖定目標 "5in1"。
3. 【智慧分塊超壓縮包】: 解除數量封印，抓取全台上市/上櫃 + 美股 S&P500 (破2000檔)。
   - 使用 Chunked Bulk Download 避免 Yahoo IP 封鎖與 GitHub 記憶體爆掉。
4. 【極端記憶體優化】: 快速清除無效/停牌股票，保護 PCA 降維順利進行。
"""

import os
import sys
import subprocess
import traceback
from datetime import datetime, timedelta
import importlib
import time
import json
import math
import requests

def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 V14.1 解除封印極速版...")
    dependencies = {
        "pandas": "pandas", "numpy": "numpy", "yfinance": "yfinance", 
        "requests": "requests", "sklearn": "scikit-learn", "matplotlib": "matplotlib",
        "gspread": "gspread", "google-auth": "google-auth",
        "google-api-python-client": "google-api-python-client", "lxml": "lxml"
    }
    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 安裝套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True
    if installed_any:
        importlib.invalidate_caches()

bootstrap()

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.ensemble import GradientBoostingRegressor
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==========================================
# 【系統配置區】
# ==========================================
CONFIG = {
    "SHEET_REPORT": "5in1",  
    "SHEET_STOCK": "stock_history",      
    "SHEET_GLOBAL": "global_market_factors", 
    "FOLDER_ID": os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
    "WINDOWS": {"SHORT": 10, "MEDIUM": 20, "LONG": 60, "ALLDATA": 0},
    "CHUNK_SIZE": 400, # 📦 每次請求的「壓縮包」大小，防 Yahoo 封鎖
    "HISTORY_DAYS": 1500 # 抓取歷史天數
}

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 【1. Google API 安全護城河】
# ==========================================
def get_google_clients():
    creds_json_str = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json_str:
        print("❌ 找不到環境變數 GSPREAD_CREDENTIALS！強制終止！")
        sys.exit(1)
        
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(creds_json_str)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gc, drive_service

def get_or_create_sheet_safe(gc, drive_service, sheet_title):
    folder_id = CONFIG["FOLDER_ID"]
    if not folder_id:
        try: return gc.open(sheet_title)
        except: return gc.create(sheet_title)

    query = f"'{folder_id}' in parents and name='{sheet_title}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    try:
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if items:
            return gc.open_by_key(items[0]['id'])
        else:
            return gc.create(sheet_title, folder_id=folder_id)
    except Exception as e:
        raise e

def robust_update(wks, cell, matrix_data):
    clean_matrix = []
    for row in matrix_data:
        clean_row = [""] if not row else row
        clean_matrix.append([val if not (isinstance(val, float) and (math.isnan(val) or math.isinf(val))) else "" for val in clean_row])
    wks.update(cell, clean_matrix)

# ==========================================
# 【2. 海量全市場股票名單獲取】
# ==========================================
def get_all_market_tickers():
    tickers = []
    print("🌐 正在動態獲取全球股票代碼清單 (無限制版)...")
    
    # A. 台股上市 (TWSE)
    try:
        res = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
        tw_data = res.json()
        twse_tickers = [f"{item['Code']}.TW" for item in tw_data if len(item['Code']) == 4]
        tickers.extend(twse_tickers)
        print(f"   ↳ 取得 {len(twse_tickers)} 檔台股上市清單。")
    except Exception as e: print(f"   ⚠️ 台股上市清單失敗: {e}")

    # B. 台股上櫃 (TPEx)
    try:
        res = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        otc_data = res.json()
        otc_tickers = [f"{item['SecuritiesCompanyCode']}.TWO" for item in otc_data if len(item['SecuritiesCompanyCode']) == 4]
        tickers.extend(otc_tickers)
        print(f"   ↳ 取得 {len(otc_tickers)} 檔台股上櫃清單。")
    except Exception as e: print(f"   ⚠️ 台股上櫃清單失敗: {e}")
        
    # C. 美股 S&P 500
    try:
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_tables = pd.read_html(sp500_url)
        us_tickers = sp500_tables[0]['Symbol'].str.replace('.', '-').tolist()
        tickers.extend(us_tickers)
        print(f"   ↳ 取得 {len(us_tickers)} 檔美股 S&P 500 清單。")
    except Exception as e: print(f"   ⚠️ 美股清單失敗: {e}")

    tickers = list(set(tickers))
    print(f"🌍 最終匯集 {len(tickers)} 檔海量股票準備進行「分塊超壓縮包」下載。")
    return tickers

# ==========================================
# 【3. 智慧分塊超壓縮包下載 (Chunked Bulk)】
# ==========================================
def fetch_massive_market_data():
    tickers = get_all_market_tickers()
    if not tickers: return pd.DataFrame()
        
    start_dt = (datetime.now() - timedelta(days=CONFIG["HISTORY_DAYS"])).strftime('%Y-%m-%d')
    end_dt = datetime.now().strftime('%Y-%m-%d')
    
    chunk_size = CONFIG["CHUNK_SIZE"]
    all_chunks_df = []
    
    print(f"📈 啟動 yfinance 分塊超壓縮下載 ({start_dt} ~ {end_dt})")
    
    # 將幾千檔股票切分成小包，避免 Yahoo IP 封鎖與 TimeOut
    for i in range(0, len(tickers), chunk_size):
        chunk_tickers = tickers[i:i+chunk_size]
        print(f"   📦 正在拉取第 {i//chunk_size + 1} 包 (包含 {len(chunk_tickers)} 檔)...", end="", flush=True)
        try:
            # yf.download 內建就是多線程超壓縮包
            df_chunk = yf.download(chunk_tickers, start=start_dt, end=end_dt, progress=False, ignore_tz=True)
            
            if 'Close' in df_chunk.columns:
                df_close = df_chunk['Close']
            else:
                df_close = df_chunk
                
            all_chunks_df.append(df_close)
            print(" 完成！")
        except Exception as e:
            print(f" 失敗略過: {e}")
        
        time.sleep(1.5) # 喘息防封鎖
        
    if not all_chunks_df: return pd.DataFrame()

    # 水平合併所有壓縮包
    print("🔄 正在融合所有壓縮包與計算變動率 (這會消耗一些記憶體)...")
    df_combined = pd.concat(all_chunks_df, axis=1)
    
    # 清理: 剃除缺失值超過 30% 的死魚股/下市股，保護記憶體
    thresh = int(len(df_combined) * 0.7)
    df_combined.dropna(axis=1, thresh=thresh, inplace=True)
    
    df_combined.reset_index(inplace=True)
    df_combined.rename(columns={'index': 'Date', 'Date': 'Date'}, inplace=True)
    df_combined['Date'] = pd.to_datetime(df_combined['Date']).dt.strftime('%Y/%m/%d')
    
    date_col = df_combined['Date']
    df_pct = df_combined.drop(columns=['Date']).pct_change().fillna(0)
    df_pct.columns = [f"{str(col)}_Ret" for col in df_pct.columns]
    df_pct.insert(0, 'Date', date_col)
    
    print(f"✅ 全市場特徵矩陣建構完畢！有效降維特徵數: {df_pct.shape[1] - 1} 檔")
    return df_pct

# ==========================================
# 【4. 核心資料集融合】
# ==========================================
def update_master_dataset(gc):
    print("\n🔄 [階段一] 開始讀取雲端核心特徵並融合海量市場數據...")
    df_stock, df_global = pd.DataFrame(), pd.DataFrame()
    
    try: df_stock = pd.DataFrame(gc.open(CONFIG["SHEET_STOCK"]).sheet1.get_all_records())
    except: pass
    try: df_global = pd.DataFrame(gc.open(CONFIG["SHEET_GLOBAL"]).sheet1.get_all_records())
    except: pass

    df_main = df_stock
    if not df_global.empty:
        df_main = pd.merge(df_main, df_global, on='Date', how='outer') if not df_main.empty else df_global

    df_massive = fetch_massive_market_data()
    if not df_massive.empty and not df_main.empty:
        df_main['Date'] = df_main['Date'].astype(str).str.replace("-", "/")
        df_massive['Date'] = df_massive['Date'].astype(str).str.replace("-", "/")
        df_main = pd.merge(df_main, df_massive, on='Date', how='left')

    df_main.replace([np.inf, -np.inf, ''], np.nan, inplace=True)
    df_main.fillna(method='ffill', inplace=True)
    df_main.fillna(0, inplace=True)
    
    df_main['Date'] = pd.to_datetime(df_main['Date'])
    df_main.sort_values('Date', inplace=True)
    df_main.reset_index(drop=True, inplace=True)
    
    print(f"✅ 資料融合完成！最終總矩陣維度: {df_main.shape[0]}列 x {df_main.shape[1]}欄")
    return df_main

# ==========================================
# 【5. 數學分析與模型競技大腦】
# ==========================================
def run_analytics_for_window(df, window_name, window_size, drive_service):
    if df.empty: return "資料集為空，跳過運算。"

    df_w = df.tail(window_size).reset_index(drop=True) if window_size > 0 else df.copy()
    if len(df_w) < 5: return f"維度 {window_name} 樣本數不足，跳過。"

    target_col = 'TWII_Close'
    if target_col not in df_w.columns:
        cols = [c for c in df_w.columns if 'Close' in c or 'TWII' in c]
        if not cols: return "找不到目標變數 TWII_Close。"
        target_col = cols[0]

    df_w['Target_Y'] = df_w[target_col].pct_change().shift(-1)
    X_raw = df_w.drop(columns=['Date', 'Target_Y', target_col], errors='ignore')
    
    # 🧯 防禦: 剔除常數(std=0)特徵，保護 PCA
    X_raw = X_raw.loc[:, X_raw.std() > 0.0001]
    
    valid_idx = df_w['Target_Y'].notna()
    X_train = X_raw[valid_idx]
    Y_train = df_w.loc[valid_idx, 'Target_Y'] * 100 
    X_today = X_raw.iloc[-1:]

    # 1. 降維魔法 PCA
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    X_today_scaled = scaler.transform(X_today)

    n_comp = min(6, X_scaled.shape[1], X_scaled.shape[0])
    pca = PCA(n_components=n_comp)
    X_pca = pca.fit_transform(X_scaled)
    X_today_pca = pca.transform(X_today_scaled)
    variance_ratio = pca.explained_variance_ratio_

    # 2. 模型競技
    models = {
        "線性 (Ridge)": Ridge(alpha=1.0),
        "支持向量機 (SVR)": SVR(kernel='rbf', C=1.0, gamma='scale'),
        "梯度提升 (GB)": GradientBoostingRegressor(n_estimators=50, random_state=42)
    }
    
    best_name, best_score, best_pred = "", -float('inf'), 0
    results_text = f"========================================\n🕒 維度: {window_name} (樣本數: {len(X_train)})\n========================================\n"
    results_text += f"🔍 [全市場 PCA 空間] 萃取 {n_comp} 主成分, 解釋變異: {sum(variance_ratio)*100:.2f}%\n\n🤖 [模型競技]\n"

    for name, model in models.items():
        model.fit(X_pca, Y_train)
        score = model.score(X_pca, Y_train)
        pred = model.predict(X_today_pca)[0]
        results_text += f"   [{name}]\n   ↳ 擬合(R²): {score:.4f} | 明日預測報酬: {pred:.2f}%\n"
        if score > best_score:
            best_score, best_name, best_pred = score, name, pred

    trend_icon = "🟢 偏多上漲" if best_pred > 0 else "🔴 偏空下跌"
    results_text += f"\n🏆 [決策中樞]\n   - 最優模型 : {best_name} (R² {best_score:.4f})\n   - 明日預期 : {best_pred:.2f}% ({trend_icon})\n\n"
    return results_text

# ==========================================
# 【6. 主控中樞】
# ==========================================
def main():
    print("\n" + "="*50)
    print("🚀 PCA_Master V14.1 解除封印全市場極速版")
    print("="*50)
    sys.stdout.flush()

    gc, drive_service = get_google_clients()
    df = update_master_dataset(gc)
    
    full_report = f"📊 V14.1 萬檔市場融合競技戰報 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    for w_name, w_size in CONFIG["WINDOWS"].items():
        print(f"\n🧠 正在解剖維度: {w_name}...")
        sys.stdout.flush()
        full_report += run_analytics_for_window(df, w_name, w_size, drive_service) + "\n"

    try:
        print(f"\n☁️ 將戰報注入 [{CONFIG['SHEET_REPORT']}]...")
        sh_report = get_or_create_sheet_safe(gc, drive_service, CONFIG["SHEET_REPORT"])
        wks_rep = sh_report.sheet1
        wks_rep.clear()
        robust_update(wks_rep, "A1", [[line] for line in full_report.split('\n')])
        wks_rep.format("A1:A200", {"textFormat": {"fontFamily": "Courier New", "fontSize": 10}})
        wks_rep.format("A1", {"textFormat": {"fontFamily": "Courier New", "fontSize": 12, "bold": True}})
        print("✅ 戰報成功注入 5in1！")
    except Exception as e:
        print(f"❌ 寫入 5in1 失敗: {str(e)}")

if __name__ == "__main__":
    main()
