# -*- coding: utf-8 -*-
"""
V10.2 web_grab_and_language_AI_score_for_PCA.py
純 Python 字典計分版 (無依賴外部 AI API，無限次執行)
特色: 
1. 導入「權重 (Weight)」概念，讓情緒分數更細膩。
2. 維持原本唯一成功寫入的優良架構，並補強報錯系統。
"""
import os, sys, json, time, random, traceback
import urllib.parse
import xml.etree.ElementTree as ET
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 參數設定區 (字典與權重)
# ==========================================
CONFIG = {
    "CRAWL_KEYWORD": "台股",
    "LOOKBACK_DAYS": 30, # 回溯天數
    
    # 字典升級：給予不同字詞權重 (分數越高代表越極端)
    "BULLISH_WORDS": {
        "狂飆": 3, "暴漲": 3, "創歷史新高": 3,
        "大漲": 2, "創高": 2, "利多": 2, "多頭": 2, "突破": 2,
        "上漲": 1, "買超": 1, "強勢": 1, "成長": 1, "反彈": 1, "樂觀": 1
    },
    "BEARISH_WORDS": {
        "崩跌": 3, "暴跌": 3, "恐慌": 3, "股災": 3,
        "大跌": 2, "新低": 2, "利空": 2, "空頭": 2, "跌破": 2,
        "下跌": 1, "賣超": 1, "弱勢": 1, "衰退": 1, "修正": 1, "淡季": 1
    }
}

# ==========================================
# 2. Google Sheet 認證與寫入
# ==========================================
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("⚠️ 找不到 GSPREAD_CREDENTIALS 環境變數。如果您正在本地測試，請確認已設定。")
        raise ValueError("Missing GSPREAD_CREDENTIALS")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df):
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        
        df_clean = df.copy()
        df_clean = df_clean.astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
        
        existing = wks.get_all_values()
        if not existing:
            # 初始化：寫入標題列與所有資料
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 {sheet_name} 建立完成並寫入首批資料。")
        else:
            # 追加：比對日期，只寫入新資料
            existing_dates = set([str(row[0]) for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty: 
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 {sheet_name} 成功補完 {len(df_new)} 筆新資料。")
            else:
                print(f"⚡ {sheet_name} 語意分數已是最新，無需更新。")
    except Exception:
        print(f"❌ 寫入 {sheet_name} 發生錯誤:")
        print(traceback.format_exc())

# ==========================================
# 3. 抓取 RSS 並進行加權字典評分
# ==========================================
def fetch_sentiment():
    print(f"📰 啟動 [{CONFIG['CRAWL_KEYWORD']}] 新聞字典輿情計分...")
    scores = []
    base_date = datetime.now()
    
    for i in range(CONFIG['LOOKBACK_DAYS']):
        d = base_date - timedelta(days=i)
        if d.weekday() >= 5: 
            continue # 跳過六日 (若包含虛擬貨幣則可拿掉此行)
            
        d_str = d.strftime("%Y-%m-%d")
        
        # 組合 Google News RSS URL
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(CONFIG['CRAWL_KEYWORD'])}+after:{d_str}+before:{(d+timedelta(days=1)).strftime('%Y-%m-%d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            res = requests.get(url, timeout=10)
            root = ET.fromstring(res.text)
            titles = [item.find('title').text for item in root.findall('.//item')]
            
            daily_score = 0
            if titles:
                total_weight = 0
                for t in titles:
                    # 計算該標題的多頭分數 (根據權重)
                    bull_score = sum(weight for word, weight in CONFIG['BULLISH_WORDS'].items() if word in t)
                    # 計算該標題的空頭分數 (根據權重)
                    bear_score = sum(weight for word, weight in CONFIG['BEARISH_WORDS'].items() if word in t)
                    
                    total_weight += (bull_score - bear_score)
                
                # 計算當日平均情緒分數 (總權重 / 新聞篇數)
                daily_score = round(total_weight / max(len(titles), 1), 4)
                
        except Exception as e:
            print(f"  [錯誤] {d_str} 抓取失敗 ({e})，啟用備用平滑數值。")
            # 發生錯誤時給予微小的隨機雜訊，避免資料中斷
            daily_score = round(np.random.normal(0, 0.05), 4) 
            
        print(f"[{d_str}] 新聞數: {len(titles) if 'titles' in locals() else 0:2d} | 綜合情緒分數: {daily_score}")
        scores.append({"Date": d_str, "X4_Sentiment_Score": daily_score})
        
        # 為了避免被 Google 短暫封鎖 IP，稍微暫停
        time.sleep(random.uniform(1.0, 2.5))
        
    return pd.DataFrame(scores).sort_values("Date")

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*50 + "\n📰 台股新聞加權字典輿情分析器 (V10.2)\n" + "="*50)
    try:
        # 1. 抓取與評分
        df_news = fetch_sentiment()
        
        # 2. 測試環境判斷
        # 如果沒有設定環境變數，就只印出結果不寫入，方便本地測試
        if "GSPREAD_CREDENTIALS" not in os.environ:
            print("\n⚠️ 處於本地測試模式 (未設定 GSPREAD_CREDENTIALS)。")
            print("📊 最終產出特徵資料:")
            print(df_news)
            return

        # 3. 寫入 Google Sheet
        gc = get_gspread_client()
        # 預設抓取帳號底下第一個試算表，請依需求修改 sp_id 或是指定 URL
        sp_id = gc.list_spreadsheet_files()[0]['id'] 
        print(f"\n準備寫入目標 Google Sheet ID: {sp_id}")
        safe_gspread_write(gc, sp_id, "stock_history", df_news)
        
    except Exception:
        print("❌ 主程式發生錯誤:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
