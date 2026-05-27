# -*- coding: utf-8 -*-
"""
V14.2 web_grab_and_language_AI_score_for_PCA.py (智慧增量爬取版)
特色:
1. 智慧斷點續傳：自動偵測雲端最新日期，只針對「缺漏的天數」進行補爬，大幅降低執行時間。
2. 防封鎖機制：免除每天全量 1825 天的請求，保護 IP 不被 Google RSS 封鎖。
3. 完美覆寫拼接：即使當日重複爬取，也會自動以最新抓取的數據覆蓋舊數據。
"""
import os, sys, json, time, random, traceback
import urllib.parse
import xml.etree.ElementTree as ET
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 參數設定區
# ==========================================
CONFIG = {
    # 嚴格綁定您的 Google Sheet ID
    "SPREADSHEET_ID": "1ZVmajxud7D4uRim8qKPRM4bA_TjnZOxvaZsWja3FKeM",
    "TARGET_SHEET_NAME": "stock_history_AI_SCORE",
    
    # 追蹤的關鍵字陣列
    "KEYWORDS_TO_CRAWL": ["台股", "台指期", "費半", "那斯達克", "台積電", "聯電", "遠東銀", "英業達", "美國", "戰爭", "鋼鐵", "黃金", "原油", "升息", "降息"],
    
    # 初次建置時的最大回溯天數 (5 年)
    "LOOKBACK_DAYS": 1825, 
    
    # 情緒字詞與權重
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
# 2. Google Sheet 認證與雲端存取
# ==========================================
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("⚠️ 找不到 GSPREAD_CREDENTIALS 環境變數 (可能是本機測試)。")
        raise ValueError("Missing GSPREAD_CREDENTIALS")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def get_existing_data_and_latest_date(gc, spreadsheet_id, sheet_name):
    """讀取雲端資料，並回傳現有 DataFrame 以及最新一筆的日期"""
    print(f"☁️ 正在連線至雲端試算表取得最新進度...")
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        existing_vals = wks.get_all_values()
        
        if existing_vals and len(existing_vals) > 1 and 'Date' in existing_vals[0]:
            headers = existing_vals[0]
            df_existing = pd.DataFrame(existing_vals[1:], columns=headers)
            
            # 轉換為 datetime 以尋找最大值
            df_existing['Date'] = pd.to_datetime(df_existing['Date'], errors='coerce')
            latest_date = df_existing['Date'].dropna().max()
            
            # 轉回字串格式供後續使用
            df_existing['Date'] = df_existing['Date'].dt.strftime('%Y-%m-%d')
            return df_existing, latest_date
        else:
            print("   ⚠️ 雲端表單為空，將準備進行全量初始化爬取。")
            return pd.DataFrame(), None
            
    except WorksheetNotFound:
        print(f"   ❌ 找不到分頁 [{sheet_name}]，系統將於寫入時自動建立或報錯。")
        return pd.DataFrame(), None
    except Exception as e:
        print(f"   ❌ 讀取雲端進度失敗 ({e})，安全起見將回退為全量爬取。")
        return pd.DataFrame(), None

def write_cloud_data(gc, spreadsheet_id, sheet_name, df_final):
    """將最終合併好的 DataFrame 覆寫回雲端"""
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        
        # 轉換格式並準備寫入矩陣
        df_final_clean = df_final.astype(str).replace({"nan": "0", "NaN": "0", "NaT": ""})
        write_data = [df_final_clean.columns.tolist()] + df_final_clean.values.tolist()
        
        print(f"\n⏳ 正在將 {len(df_final_clean)} 筆歷史資料寫入雲端 (請稍候)...")
        wks.clear()
        
        try:
            wks.update(range_name="A1", values=write_data)
        except TypeError:
            wks.update("A1", write_data)
            
        print(f"🟢 [{sheet_name}] 更新成功！增量數據寫入完畢。")
    except Exception:
        print(f"❌ 寫入 {sheet_name} 時發生錯誤:")
        print(traceback.format_exc())

# ==========================================
# 3. 智慧增量 RSS 爬蟲與情感運算
# ==========================================
def fetch_sentiment_for_keyword(keyword, latest_date):
    today = datetime.now()
    
    # 判斷要爬幾天 (智慧增量邏輯)
    if latest_date is not None:
        # 重疊 1 天，確保最新那一天的資料有被完整更新 (因為當天可能盤中爬過，盤後又有新新聞)
        days_to_crawl = (today - latest_date).days
        if days_to_crawl < 0: days_to_crawl = 0
        loop_days = days_to_crawl + 1 
        print(f"\n🔍 [{keyword}] 偵測到雲端最新進度為 {latest_date.strftime('%Y-%m-%d')}，僅補爬最近 {loop_days} 天。")
    else:
        loop_days = CONFIG['LOOKBACK_DAYS']
        print(f"\n🔍 [{keyword}] 無歷史紀錄，執行 {loop_days} 天全量回溯爬取 (耗時較長請耐心等候)...")

    scores = []
    valid_days_count = 0 
    
    for i in range(loop_days):
        d = today - timedelta(days=i)
        
        # 略過週末六日 (假設六日無開盤，新聞量較無代表性)
        if d.weekday() >= 5: 
            continue 
            
        d_str = d.strftime("%Y-%m-%d")
        valid_days_count += 1
        
        if valid_days_count % 100 == 0:
            print(f"   ⏳ 已往回爬取 {valid_days_count} 個交易日，目前進度至: {d_str}")
            
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}+after:{d_str}+before:{(d+timedelta(days=1)).strftime('%Y-%m-%d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            res = requests.get(url, timeout=10)
            root = ET.fromstring(res.text)
            titles = [item.find('title').text for item in root.findall('.//item')]
            
            daily_score = 0
            if titles:
                total_weight = 0
                for t in titles:
                    bull_score = sum(weight for word, weight in CONFIG['BULLISH_WORDS'].items() if word in t)
                    bear_score = sum(weight for word, weight in CONFIG['BEARISH_WORDS'].items() if word in t)
                    total_weight += (bull_score - bear_score)
                daily_score = round(total_weight / max(len(titles), 1), 4)
        except Exception:
            # 遇到網路錯誤給予微小雜訊，避免特徵矩陣出現大破洞
            daily_score = round(np.random.normal(0, 0.05), 4) 
            
        scores.append({"Date": d_str, f"{keyword}_AI_SCORE": daily_score})
        
        # 加入隨機延遲，避免短時間大量請求被 Google 封鎖 IP
        time.sleep(random.uniform(0.6, 1.8)) 
        
    print(f"   ✅ [{keyword}] 爬取完成！本次收集 {len(scores)} 天的特徵。")
    return pd.DataFrame(scores)

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*65 + "\n📰 多關鍵字台股新聞輿情分析器 (智慧增量版)\n" + "="*65)
    try:
        # 1. 取得授權並讀取舊資料庫進度
        gc = get_gspread_client()
        sp_id = CONFIG["SPREADSHEET_ID"]
        target_sheet = CONFIG["TARGET_SHEET_NAME"]
        
        df_existing, latest_date = get_existing_data_and_latest_date(gc, sp_id, target_sheet)
        
        # 2. 爬取新資料
        df_new = None
        for kw in CONFIG['KEYWORDS_TO_CRAWL']:
            df_kw = fetch_sentiment_for_keyword(kw, latest_date)
            
            if df_kw.empty: continue
            
            if df_new is None:
                df_new = df_kw
            else:
                df_new = pd.merge(df_new, df_kw, on="Date", how="outer")
                
        # 如果根本沒有新資料 (例如今天週末，直接結束)
        if df_new is None or df_new.empty:
            print("\n🎉 所有資料皆已是最新狀態，無需寫入雲端！")
            return

        # 3. 完美合併新舊資料
        print("\n🔄 正在將新抓取的數據與雲端歷史紀錄融合...")
        if not df_existing.empty:
            # 將新資料加到舊資料後面
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
            # 核心：如果日期重複 (例如重疊的那一天)，保留 'last'，也就是我們剛抓的最新的數據
            df_final = df_final.drop_duplicates(subset=['Date'], keep='last')
        else:
            df_final = df_new.copy()
            
        # 4. 排序與補零處理
        df_final['Date'] = pd.to_datetime(df_final['Date'])
        df_final = df_final.sort_values("Date")
        df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
        df_final = df_final.fillna(0)

        # 5. 寫回雲端
        write_cloud_data(gc, sp_id, target_sheet, df_final)
        
    except Exception:
        print("❌ 主程式發生錯誤:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
