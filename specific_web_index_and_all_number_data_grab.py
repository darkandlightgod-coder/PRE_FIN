# -*- coding: utf-8 -*-
"""
v10.0 web_grab_and_language_AI_score_for_PCA.py
【第二步】：新聞輿情爬取與語意分析 (支援 13 檔個股與大盤多空詞彙加權)
"""
import os, sys, json, traceback, requests, time, random
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import urllib.parse
import xml.etree.ElementTree as ET
import gspread
from google.oauth2.service_account import Credentials

KEYWORDS = ["台股", "台積電", "聯電", "英業達", "中鋼", "NVIDIA", "TESLA", "INTEL", "Apple", "Microsoft", "Amazon", "Eli Lilly", "Novo Nordisk", "Toyota"]
BULLISH = ["上漲", "大漲", "創高", "買超", "利多", "強勢", "多頭", "成長", "反彈", "樂觀", "突破", "優於預期"]
BEARISH = ["下跌", "大跌", "新低", "賣超", "利空", "弱勢", "空頭", "衰退", "虧損", "修正", "跌破", "賣壓", "不如預期"]

def get_moat_sheet():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(gc.list_spreadsheet_files()[0]['id'])

def smart_append(sh, sheet_name, df):
    if df.empty: return
    try:
        try: wks = sh.worksheet(sheet_name)
        except: wks = sh.add_worksheet(title=sheet_name, rows="1000", cols="30")
        df = df.fillna("")
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df.columns.values.tolist()] + df.values.tolist())
        else:
            existing_dates = set([row[0] for row in existing[1:] if row])
            df = df[~df['Date'].isin(existing_dates)]
            if not df.empty: wks.append_rows(df.values.tolist())
    except Exception as e:
        traceback.print_exc()

def fetch_news_sentiment(keyword, days_back=30):
    """Google News RSS 免 API Key 爬蟲與本地語意計分"""
    print(f"📰 正在爬取 [{keyword}] 的新聞輿情...")
    scores = []
    base_date = datetime.now()
    
    for i in range(days_back):
        target_date = base_date - timedelta(days=i)
        d_str = target_date.strftime("%Y-%m-%d")
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}+after:{d_str}+before:{(target_date+timedelta(days=1)).strftime('%Y-%m-%d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            res = requests.get(url, timeout=10)
            root = ET.fromstring(res.text)
            titles = [item.find('title').text for item in root.findall('.//item')]
            
            daily_score = 0
            for t in titles:
                bull = sum(1 for w in BULLISH if w in t)
                bear = sum(1 for w in BEARISH if w in t)
                daily_score += (bull - bear)
            
            scores.append({"Date": d_str, f"Sent_{keyword}": round(daily_score / max(len(titles), 1), 4)})
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            scores.append({"Date": d_str, f"Sent_{keyword}": 0.0})
    
    return pd.DataFrame(scores)

def main():
    print("="*50 + "\n🚀 v10.0 [2/5] 輿情語意 AI 計分系統\n" + "="*50)
    sh = get_moat_sheet()
    
    df_final = pd.DataFrame()
    for kw in KEYWORDS[:5]: # 為防超時，優先採集前 5 大權值標的，其餘標的可依序加入
        df_kw = fetch_news_sentiment(kw, days_back=15) # 追溯15天空值
        if df_final.empty: df_final = df_kw
        else: df_final = pd.merge(df_final, df_kw, on="Date", how="outer")
        
    df_final = df_final.sort_values("Date")
    smart_append(sh, "stock_history", df_final)
    print("✅ 輿情計分完畢，寫入 stock_history。")

if __name__ == "__main__":
    main()
