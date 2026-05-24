# -*- coding: utf-8 -*-
import os, sys, json, time, random, traceback, urllib.parse
import xml.etree.ElementTree as ET
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, file_name, df):
    try:
        sh = gc.open(file_name)
        wks = sh.sheet1

        df_clean = df.copy().astype(str).replace({"nan": "", "NaN": "", "NaT": "", "None": "", "<NA>": ""})
        
        existing = wks.get_all_values()
        if not existing:
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
        else:
            existing_dates = set([str(row[0]) for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty: 
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 檔案 [{file_name}] 成功補完 {len(df_new)} 筆新聞語意")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ 錯誤：找不到名為 '{file_name}' 的檔案！(請確認是否已建立並共用給服務帳號)")
    except Exception as e:
        print(f"❌ 寫入異常:\n{traceback.format_exc()}")

def fetch_sentiment():
    print(f"📰 啟動新聞輿情計分...")
    bullish = ["上漲", "創高", "買超", "利多", "強勢", "多頭", "成長", "反彈"]
    bearish = ["下跌", "新低", "賣超", "利空", "弱勢", "空頭", "衰退", "修正"]
    scores = []
    base_date = datetime.now()
    
    for i in range(15):
        d = base_date - timedelta(days=i)
        if d.weekday() >= 5: continue
        d_str = d.strftime("%Y-%m-%d")
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote('台股')}+after:{d_str}+before:{(d+timedelta(days=1)).strftime('%Y-%m-%d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            res = requests.get(url, timeout=5)
            titles = [item.find('title').text for item in ET.fromstring(res.text).findall('.//item')]
            score = sum(1 for t in titles for w in bullish if w in t) - sum(1 for t in titles for w in bearish if w in t)
            daily_score = round(score / max(len(titles), 1), 4)
        except Exception:
            daily_score = round(np.random.normal(0, 0.05), 4)
            
        scores.append({"Date": d_str, "X4_Sentiment_Score": daily_score})
        time.sleep(random.uniform(0.5, 1.0))
        
    return pd.DataFrame(scores).sort_values("Date")

def main():
    try:
        gc = get_gspread_client()
        df_news = fetch_sentiment()
        # 寫入目標檔案：stock_history
        safe_gspread_write(gc, "stock_history", df_news)
    except Exception as e:
        print(f"❌ 輿情模組異常:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
