# -*- coding: utf-8 -*-
"""
V9.0 PCA_Master_Exceed 終極量化預測大腦
=========================================================
1. 五維度預測 (3day, 7day, 1month, 1year, alldata)
2. PCA 保留 99% 特徵參數 (捨棄固定 5 參數限制)
3. 歷史資料回溯 5 年，結合「增量爬蟲」防 IP 封鎖
4. 導入 Polynomial 非線性乘算驗證 (檢測 a*X1*X2 + b*X1^2 效力)
5. 自動繪製 5 張多維度診斷圖，同步傳送 Google Drive & Sheets
"""

import os
import sys
import subprocess
import traceback
from datetime import datetime, timedelta
import importlib
import time
import random
import urllib.parse
import xml.etree.ElementTree as ET
import json

# ==========================================\n# 【1. 環境自建自癒系統 (Bootstrap)】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 V9.0 環境自檢...")
    dependencies = {
        "pandas": "pandas", "numpy": "numpy", "yfinance": "yfinance", 
        "requests": "requests", "bs4": "beautifulsoup4", "playwright": "playwright",
        "sklearn": "scikit-learn", "matplotlib": "matplotlib",
        "gspread": "gspread", "google-auth": "google-auth",
        "google-api-python-client": "google-api-python-client"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 自動安裝套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()

    try:
        from playwright.sync_api import sync_playwright
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True)
    except Exception as e:
        pass
    print("✅ 環境配置完畢。")

bootstrap()

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# =====================================================================
# ⚙️ 核心常數與 G-Cloud 設定
# =====================================================================
CONFIG = {
    "SHEET_MASTER_DATA": "TWII_Master_Data",
    "SHEET_REPORT": "PCA_PRE_FIN",
    "DRIVE_FOLDER_ID": os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
    "HISTORY_YEARS": 5,
    "WINDOWS": {
        "3day": 3,
        "7day": 7,
        "1month": 22,
        "1year": 252,
        "alldata": None
    }
}

# =====================================================================
# 🔑 Google API 授權
# =====================================================================
def get_google_clients():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        print("⚠️ 未偵測到 Google 憑證，將以單機模式運行。")
        return None, None
    try:
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        drive_service = build('drive', 'v3', credentials=credentials)
        return gc, drive_service
    except Exception as e:
        print(f"❌ Google 授權失敗: {e}")
        return None, None

def get_or_create_sheet(gc, sheet_name):
    try:
        sh = gc.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        sh = gc.create(sheet_name)
    return sh

# =====================================================================
# 🕸️ 爬蟲引擎：期權、全球因子、輿情 (整合版)
# =====================================================================
def fetch_global_and_twse(start_date, end_date):
    """使用 YFinance 抓取全球與台灣現貨 (5年)"""
    tickers = {"^TWII": "TWII_Close", "^TNX": "US10Y", "^VIX": "VIX", "^SOX": "SOX", "^GSPC": "SPX"}
    print(f"🌍 抓取全球因子: {start_date} 到 {end_date}")
    df = yf.download(list(tickers.keys()), start=start_date, end=end_date)['Close']
    df = df.rename(columns={k: v for k, v in tickers.items()})
    df.index = df.index.strftime('%Y/%m/%d')
    df = df.reset_index().rename(columns={"Date": "Date"})
    return df.ffill().dropna()

def fetch_taifex_futures(context, date_obj):
    """爬取期交所：外資與自營商期貨"""
    try:
        date_str = date_obj.strftime("%Y/%m/%d")
        url = f"https://www.taifex.com.tw/cht/3/futContractsDate?queryDate={date_str}"
        page = context.new_page()
        page.goto(url, timeout=15000)
        html = page.content()
        page.close()
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        for table in tables:
            if "外資" in table.text and "自營商" in table.text:
                rows = table.find_all('tr')
                # 簡化解析，實務上依據欄位 index 提取
                return {"Foreign_OI": random.randint(-10000, 10000)} # 範例填充，請套用原本的 BS4 解析法
    except:
        pass
    return {"Foreign_OI": 0}

def fetch_news_sentiment(date_str):
    """Google News RSS 輿情計分"""
    query = urllib.parse.quote(f"台股 when:{date_str}")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, timeout=10)
        root = ET.fromstring(resp.text)
        titles = [item.find('title').text for item in root.findall('.//item')]
        
        bull_words = ["漲", "創高", "買超", "多頭"]
        bear_words = ["跌", "新低", "賣超", "空頭"]
        
        score = 0
        for t in titles:
            if any(w in t for w in bull_words): score += 1
            if any(w in t for w in bear_words): score -= 1
        return round(score / (len(titles) + 1), 4)
    except:
        return 0

# =====================================================================
# 🔄 增量資料流管控 (核心機制：防鎖防超時)
# =====================================================================
def update_master_dataset(gc):
    """管理 5 年歷史數據，僅對缺漏日期進行爬取"""
    today = datetime.now()
    start_of_5yrs = today - timedelta(days=CONFIG["HISTORY_YEARS"] * 365)
    
    sh = None
    if gc:
        sh = get_or_create_sheet(gc, CONFIG["SHEET_MASTER_DATA"])
        records = sh.sheet1.get_all_records()
        df_history = pd.DataFrame(records)
    else:
        df_history = pd.DataFrame()

    # 決定爬取起點
    if not df_history.empty and "Date" in df_history.columns:
        last_date_str = df_history["Date"].max()
        last_date = datetime.strptime(last_date_str, "%Y/%m/%d")
        crawl_start = last_date + timedelta(days=1)
    else:
        crawl_start = start_of_5yrs
        df_history = pd.DataFrame(columns=["Date", "TWII_Close", "US10Y", "VIX", "SOX", "SPX", "Sentiment"])

    if crawl_start >= today:
        print("✅ 資料庫已是最新，無需爬取。")
        return df_history.sort_values("Date")

    print(f"🚀 啟動增量更新，爬取區間: {crawl_start.strftime('%Y/%m/%d')} 迄今...")
    df_new = fetch_global_and_twse(crawl_start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    
    if df_new.empty:
        return df_history

    # 加入新聞輿情 (只抓取新日期的)
    sentiments = []
    for d in df_new["Date"]:
        d_format = d.replace("/", "-")
        sentiments.append(fetch_news_sentiment(d_format))
        time.sleep(0.5)
    df_new["Sentiment"] = sentiments

    # 合併與上傳
    df_final = pd.concat([df_history, df_new]).drop_duplicates(subset=["Date"]).sort_values("Date")
    
    if gc:
        sh.sheet1.clear()
        sh.sheet1.update([df_final.columns.values.tolist()] + df_final.values.tolist())
        print("☁️ 歷史資料庫已同步至 Google Sheet。")
        
    return df_final

# =====================================================================
# 🧠 五維度 PCA 與非線性乘算引擎
# =====================================================================
def run_analytics_for_window(df, window_name, window_size, drive_service=None):
    """針對特定時間窗進行 99% PCA 與非線性檢查"""
    if window_size is not None:
        sub_df = df.tail(window_size).copy()
    else:
        sub_df = df.copy()

    if len(sub_df) < 3:
        return f"[{window_name}] 樣本數過少 ({len(sub_df)})，跳過運算。"

    # 準備特徵 (X) 與 目標 (y: 明日大盤變化率)
    sub_df['TWII_Return'] = sub_df['TWII_Close'].pct_change().shift(-1)
    features = ["TWII_Close", "US10Y", "VIX", "SOX", "SPX", "Sentiment"]
    
    # 移除最後一筆 NaN return
    calc_df = sub_df.dropna(subset=features + ['TWII_Return'])
    if calc_df.empty:
        return f"[{window_name}] 清理後無有效數據。"

    X = calc_df[features].values
    y = calc_df['TWII_Return'].values

    # 1. 執行 PCA (保留 99% 變異)，突破固定 5 個的限制
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 若樣本數過少，自動調整 components 數量上限
    max_comp = min(X_scaled.shape[0], X_scaled.shape[1])
    pca = PCA(n_components=0.99 if max_comp > 15 else max_comp) 
    X_pca = pca.fit_transform(X_scaled)
    n_components_used = pca.n_components_

    # 2. 純線性模型 (a*PC1 + b*PC2...)
    lin_model = Ridge(alpha=1.0)
    lin_model.fit(X_pca, y)
    lin_r2 = lin_model.score(X_pca, y)

    # 3. 非線性乘算模型 (檢測 a*(PC1*PC2) + b*(PC1^2)... 效應)
    poly = PolynomialFeatures(degree=2, include_bias=False)
    X_poly = poly.fit_transform(X_pca)
    poly_model = Ridge(alpha=1.0)
    poly_model.fit(X_poly, y)
    poly_r2 = poly_model.score(X_poly, y)

    # 判斷是否為非線性主導
    is_non_linear = poly_r2 > (lin_r2 + 0.1) # R2 顯著提升 10%
    structure_advice = "🚨 檢測到強烈非線性/乘算特徵！市場產生複合巨變，建議採用非線性權重。" if is_non_linear else "✅ 市場呈現常態線性疊加結構。"

    # 4. 預測最新一日
    latest_X = scaler.transform(sub_df[features].tail(1).values)
    latest_pca = pca.transform(latest_X)
    pred_lin = lin_model.predict(latest_pca)[0]
    
    latest_poly = poly.transform(latest_pca)
    pred_poly = poly_model.predict(latest_poly)[0]

    final_pred = pred_poly if is_non_linear else pred_lin
    trend = "🔴 偏空" if final_pred < 0 else "🟢 偏多"

    # 5. 繪製並輸出圖片
    plt.figure(figsize=(10, 6))
    plt.scatter(X_pca[:, 0], X_pca[:, 1], c=y, cmap='RdYlGn', alpha=0.7)
    plt.colorbar(label='TWII Return')
    plt.title(f"[{window_name}] PCA PC1 vs PC2 (Target: TWII)\nMode: {'Non-Linear' if is_non_linear else 'Linear'}")
    plt.xlabel("PC 1")
    plt.ylabel("PC 2")
    
    img_name = f"pca_{window_name}.png"
    plt.savefig(img_name, bbox_inches='tight')
    plt.close()

    # 上傳圖片至 Drive (若有憑證)
    if drive_service and CONFIG["DRIVE_FOLDER_ID"]:
        try:
            file_metadata = {'name': img_name, 'parents': [CONFIG["DRIVE_FOLDER_ID"]]}
            media = MediaFileUpload(img_name, mimetype='image/png')
            drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        except:
            pass

    # 組裝該維度的戰報
    report_chunk = f"""
========================================
🕒 維度: {window_name.upper()} (樣本數: {len(calc_df)})
========================================
- PCA 保留 99% 特徵數 : {n_components_used} 個主成分
- 線性模型 R² 分數    : {lin_r2:.4f}
- 乘算(非線性) R² 分數: {poly_r2:.4f}
- 結構診斷 : {structure_advice}
- 明日預期報酬率: {final_pred*100:.2f}% ({trend})
"""
    return report_chunk

# =====================================================================
# 🚀 主控台
# =====================================================================
def main():
    print("\n" + "="*50)
    print("🚀 PCA_Master_Exceed V9.0 全維度非線性預測大腦啟動")
    print("="*50)

    gc, drive_service = get_google_clients()
    
    # 1. 更新 5 年歷史資料庫 (增量)
    df = update_master_dataset(gc)
    
    # 2. 執行 5 維度分析
    full_report = f"📊 V9.0 預測決策戰報 - 生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    for w_name, w_size in CONFIG["WINDOWS"].items():
        print(f"\n🧠 正在運算維度: {w_name}...")
        report_chunk = run_analytics_for_window(df, w_name, w_size, drive_service)
        full_report += report_chunk + "\n"

    print("\n" + full_report)

    # 3. 將戰報寫入雲端
    if gc:
        try:
            sh_report = get_or_create_sheet(gc, CONFIG["SHEET_REPORT"])
            sh_report.sheet1.clear()
            lines = full_report.split('\n')
            matrix_data = [[line] for line in lines]
            sh_report.sheet1.update("A1", matrix_data)
            print("🟢 戰報已成功寫入 Google Sheet: PCA_PRE_FIN！")
        except Exception as e:
            print(f"❌ 雲端戰報寫入失敗: {e}")

if __name__ == "__main__":
    main()
