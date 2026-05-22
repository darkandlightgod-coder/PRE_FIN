# -*- coding: utf-8 -*-
"""
v10.0 web_grab_and_language_AI_score_for_PCA.py
負責抓取 13 檔個股與大盤新聞，進行語意 AI 評分，寫入 stock_history
"""
import os, sys, json, traceback, requests, time, random
from datetime import datetime, timedelta
import pandas as pd
import urllib.parse
import xml.etree.ElementTree as ET
import gspread
from google.oauth2.service_account import Credentials

KEYWORDS = ["台股", "台積電", "聯電", "英業達", "中鋼", "NVIDIA", "TESLA", "INTEL", "Apple", "Microsoft", "Amazon", "Eli Lilly", "Novo Nordisk", "Toyota"]
BULLISH = ["上漲", "大漲", "創高", "買超", "利多", "強勢", "多頭", "反彈", "樂觀", "突破", "優於預期"]
BEARISH = ["下跌", "大跌", "新低", "賣超", "利空", "弱勢", "空頭", "衰退", "修正", "跌破", "不如預期"]

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df=None):
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        df_clean = df.fillna("")
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
        else:
            existing_dates = set([row[0] for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty: wks.append_rows(df_new.values.tolist())
            print(f"🟢 {sheet_name} 成功補完 {len(df_new)} 筆新聞語意")
    except Exception as e:
        print(f"❌ 寫入 {sheet_name} 失敗: {e}")

def fetch_news_sentiment(keyword, days_back=30):
    print(f"📰 爬取 [{keyword}] 新聞輿情...")
    scores = []
    base_date = datetime.now()
    
    for i in range(days_back):
        d = base_date - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}+after:{d_str}+before:{(d+timedelta(days=1)).strftime('%Y-%m-%d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            res = requests.get(url, timeout=5)
            root = ET.fromstring(res.text)
            titles = [item.find('title').text for item in root.findall('.//item')]
            
            daily_score = 0
            for t in titles:
                daily_score += sum(1 for w in BULLISH if w in t) - sum(1 for w in BEARISH if w in t)
            
            scores.append({"Date": d_str, f"Sent_{keyword}": round(daily_score / max(len(titles), 1), 4)})
            time.sleep(random.uniform(0.5, 1.5))
        except:
            scores.append({"Date": d_str, f"Sent_{keyword}": 0.0})
    return pd.DataFrame(scores)

def main():
    print("="*50 + "\n🚀 v10.0 [模組 3] 輿情語意 AI 計分\n" + "="*50)
    gc = get_gspread_client()
    sp_id = gc.list_spreadsheet_files()[0]['id']
    
    df_final = pd.DataFrame()
    for kw in KEYWORDS[:6]: # 為防止 Actions 超時，取前 6 大權值與大盤
        df_kw = fetch_news_sentiment(kw, days_back=60) # 追溯兩個月空值
        if df_final.empty: df_final = df_kw
        else: df_final = pd.merge(df_final, df_kw, on="Date", how="outer")
        
    df_final = df_final.sort_values("Date")
    safe_gspread_write(gc, sp_id, "stock_history", df_final)

if __name__ == "__main__":
    main()
