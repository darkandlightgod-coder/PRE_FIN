# -*- coding: utf-8 -*-
"""
V16 PCA_Master_Exceed 數據金庫版 (Data Vault Edition)
=========================================================
本版本將所有外部數據的爬取，加上了「Google Sheets 智能快取與同步」機制：
1. 【讀取緩存】: 優先讀取 Google Sheet 中已有的歷史數據。
2. 【差異抓取】: 自動比對日期，只爬取「Sheet 中沒有的最新日期 (Delta)」。
3. 【回寫更新】: 將新抓到的數據 Append 回寫到指定 Sheet，達成資料多次利用。
4. 【無縫融合】: 將最新完整的宏觀、新聞、台股矩陣送入 PCA 降維大腦。
"""

import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 【設定區】: 雲端金鑰與指定 Google Sheet
# ==========================================
CONFIG = {
    # 請填入您用來儲存所有 Raw Data 的 Google Spreadsheet ID
    "SPREADSHEET_KEY": "您的_Google_Sheet_ID_請填這",
    
    # 各模組對應的 Sheet 分頁名稱
    "SHEETS": {
        "MACRO": "Global_Macro_Raw",      # 原 GLOBAL_Market_Factors 存放區
        "NEWS": "News_Sentiment_Raw",     # 原 新聞語意評分 存放區
        "OPTIONS": "Taifex_Options_Raw",  # 原 期權籌碼 存放區
        "REPORT": "PCA_PRE_FIN"           # 最終決策戰報
    }
}

CREDENTIALS_FILE = 'credentials.json' # 您的 Google 憑證檔案

MACRO_TICKERS = {
    "GC=F": "黃金", "SI=F": "白銀", "CL=F": "原油", 
    "ZC=F": "玉米", "ZW=F": "小麥", "BDRY": "散裝航運", 
    "^TNX": "美債10Y", "^VIX": "恐慌指數", "^SOX": "費半", "^GSPC": "標普500"
}

# ==========================================
# 【核心 0】: Google Sheets 連線與工具
# ==========================================
def get_gspread_client():
    """取得 Google Sheets 操作權限"""
    print("🔑 正在驗證 Google 憑證...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        print("   ✅ Google API 授權成功！")
        return gc
    except Exception as e:
        print(f"   ❌ 憑證讀取失敗: {e}")
        return None

def get_or_create_worksheet(sh, sheet_name):
    """取得指定的 Sheet 分頁，若不存在則建立"""
    try:
        return sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"   ⚠️ 找不到分頁 [{sheet_name}]，自動建立中...")
        return sh.add_worksheet(title=sheet_name, rows="1000", cols="50")

# ==========================================
# 【核心 1】: 新聞語意 AI 計分 (智能同步版)
# ==========================================
def sync_news_sentiment(gc, sh):
    print("\n📰 [模組 1] 啟動新聞語意智能同步...")
    wks = get_or_create_worksheet(sh, CONFIG["SHEETS"]["NEWS"])
    existing_data = wks.get_all_records()
    df_history = pd.DataFrame(existing_data) if existing_data else pd.DataFrame(columns=["Date", "Sentiment_Score"])
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 檢查今天是否已經抓過
    if not df_history.empty and today_str in df_history["Date"].values:
        print(f"   ✅ 今日 ({today_str}) 新聞情緒已存在於雲端，免重複爬取。")
        return df_history
    
    # 執行爬蟲
    print(f"   🔍 雲端無今日數據，開始擷取今日 Google News...")
    keyword = "台股 OR 台積電 OR 大盤"
    url = f"https://news.google.com/rss/search?q={keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    score = 0
    try:
        response = requests.get(url, timeout=10)
        root = ET.fromstring(response.content)
        titles = [item.find('title').text for item in root.findall('.//item')]
        
        bull_words = ["上漲", "大漲", "創高", "買超", "利多", "強勢", "多頭", "成長", "反彈"]
        bear_words = ["下跌", "大跌", "新低", "賣超", "利空", "弱勢", "空頭", "衰退", "修正"]
        
        for title in titles:
            score += sum(1 for w in bull_words if w in title)
            score -= sum(1 for w in bear_words if w in title)
        
        normalized_score = round(max(min(score / 20.0, 1.0), -1.0), 4)
        print(f"   ➤ 計算完成，今日分數: {normalized_score}")
    except Exception as e:
        print(f"   ⚠️ 抓取失敗 ({e})，給予預設值 0")
        normalized_score = 0.0

    # 回寫到 DataFrame 與 Google Sheet
    new_row = pd.DataFrame([{"Date": today_str, "Sentiment_Score": normalized_score}])
    df_history = pd.concat([df_history, new_row], ignore_index=True)
    
    wks.clear()
    wks.update([df_history.columns.values.tolist()] + df_history.values.tolist())
    print(f"   ☁️ 已將最新新聞情緒同步至 Google Sheet [{CONFIG['SHEETS']['NEWS']}]")
    
    # 將 Date 設為 index 以利後續合併
    df_history['Date'] = pd.to_datetime(df_history['Date'])
    df_history.set_index('Date', inplace=True)
    return df_history

# ==========================================
# 【核心 2】: 全球宏觀因子 (智能同步版)
# ==========================================
def sync_macro_factors(gc, sh):
    print("\n🌍 [模組 2] 啟動全球宏觀因子智能同步...")
    wks = get_or_create_worksheet(sh, CONFIG["SHEETS"]["MACRO"])
    existing_data = wks.get_all_records()
    df_history = pd.DataFrame(existing_data)
    
    if not df_history.empty:
        df_history['Date'] = pd.to_datetime(df_history['Date'])
        last_date = df_history['Date'].max()
        print(f"   ✅ 讀取雲端快取，最後更新日期: {last_date.strftime('%Y-%m-%d')}")
        # 若最後更新日距今小於1天，視為已最新
        if (datetime.now() - last_date).days <= 1:
            print("   🎉 雲端數據已是最新，無需向 Yahoo Finance 請求。")
            df_history.set_index('Date', inplace=True)
            return df_history
        start_fetch_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        print("   ⚠️ 雲端無歷史資料，將進行首次深度採集 (過去3個月)...")
        start_fetch_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    print(f"   🔍 正在自 {start_fetch_date} 起向 yfinance 抓取缺漏數據 (Delta)...")
    tickers = list(MACRO_TICKERS.keys())
    try:
        df_new = yf.download(tickers, start=start_fetch_date, interval="1d")['Close']
        df_new.dropna(how='all', inplace=True)
        df_new.index = pd.to_datetime(df_new.index).normalize()
        
        if not df_new.empty:
            df_new.reset_index(inplace=True)
            df_new.rename(columns={'index': 'Date', 'Date': 'Date'}, inplace=True)
            
            # 合併新舊數據並去重
            if not df_history.empty:
                df_combined = pd.concat([df_history, df_new]).drop_duplicates(subset=['Date'], keep='last')
            else:
                df_combined = df_new
                
            df_combined = df_combined.sort_values('Date').ffill()
            
            # 準備寫入 Google Sheet (日期需轉字串)
            df_upload = df_combined.copy()
            df_upload['Date'] = df_upload['Date'].dt.strftime("%Y-%m-%d")
            # 處理 NaN 防止上傳報錯
            df_upload = df_upload.fillna("") 
            
            wks.clear()
            wks.update([df_upload.columns.values.tolist()] + df_upload.values.tolist())
            print(f"   ☁️ 已將缺漏的宏觀數據補齊並寫入 [{CONFIG['SHEETS']['MACRO']}]")
            
            df_combined.set_index('Date', inplace=True)
            return df_combined
    except Exception as e:
        print(f"   ❌ 抓取或同步失敗: {e}")
    
    if not df_history.empty:
        df_history.set_index('Date', inplace=True)
    return df_history

# ==========================================
# 【核心 3】: 台股全矩陣 (示意: 日後可串接您的 CSV)
# ==========================================
def fetch_tw_market_matrix():
    print("\n🕸️ [模組 3] 載入台股 2000 檔矩陣 (範例簡化)...")
    core_tw_tickers = ["^TWII", "2330.TW", "2317.TW", "2603.TW"]
    df_tw = yf.download(core_tw_tickers, period="3mo", interval="1d")['Close']
    df_tw.index = pd.to_datetime(df_tw.index).normalize()
    df_tw = df_tw.ffill().bfill()
    return df_tw

# ==========================================
# 【主中樞】: 降維與分析
# ==========================================
def main():
    print("\n" + "="*50)
    print("🚀 PCA_Master_Exceed V16 啟動：數據金庫智能同步版")
    print("="*50)
    
    gc = get_gspread_client()
    if not gc:
        print("系統無憑證，強制終止。")
        return
        
    try:
        sh = gc.open_by_key(CONFIG["SPREADSHEET_KEY"])
    except Exception as e:
        print(f"無法開啟 Spreadsheet ({e})，請確認 SPREADSHEET_KEY 是否正確。")
        return

    # 1. 智能同步與獲取數據 (皆已包含快取防護)
    df_news = sync_news_sentiment(gc, sh)
    df_macro = sync_macro_factors(gc, sh)
    df_tw = fetch_tw_market_matrix()
    
    # 2. 特徵矩陣大融合 (對齊日期)
    print("\n🧬 [融合階段] 正在將所有 Raw Data 依照日期對齊融合...")
    df_merged = pd.concat([df_macro, df_tw, df_news], axis=1).sort_index()
    
    # 去除假日空值並向前填充
    df_merged.ffill(inplace=True)
    df_merged.dropna(inplace=True)
    
    print(f"   ➤ 矩陣融合完成！最終運算維度: {df_merged.shape[1]}，有效交易天數: {df_merged.shape[0]}")
    
    # 3. PCA 降維運算
    print("\n🧠 [PCA 大腦] 正在執行多維度降維萃取...")
    scaler = StandardScaler()
    scaled_data = scaler.fit_transform(df_merged)
    
    pca = PCA(n_components=5)
    pca_result = pca.fit_transform(scaled_data)
    variance_ratio = sum(pca.explained_variance_ratio_) * 100
    
    print(f"   ➤ PCA 萃取成功！前 5 大主成分解釋了市場 {variance_ratio:.2f}% 的變異。")
    print("   🎉 流程執行完畢！外部原始資料 (Raw Data) 已妥善保存於雲端，下次執行將極速讀取。")

if __name__ == "__main__":
    main()
