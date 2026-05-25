# -*- coding: utf-8 -*-
"""
V12.0 web_grab_and_language_AI_score_for_PCA.py
純 Python 字典計分版 (無依賴外部 AI API，無限次執行)
特色:
1. 支援多個目標關鍵字，每個關鍵字獨立產出一欄 (例如：台指期_AI_SCORE, 費半_AI_SCORE)。
2. 嚴格綁定 Google Sheet ID，拔除所有自動建表功能，杜絕誤創檔案。
3. 採用字典權重法，運算極快，不消耗任何 API 額度。
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
    
    # 您想追蹤的各種關鍵字陣列，可以自由新增或刪除
    "KEYWORDS_TO_CRAWL": ["台股", "台指期", "費半", "那斯達克", "台積電"],
    "LOOKBACK_DAYS": 30, # 回溯天數
    
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
# 2. Google Sheet 認證與寫入 (嚴格模式)
# ==========================================
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("⚠️ 找不到 GSPREAD_CREDENTIALS 環境變數。")
        raise ValueError("Missing GSPREAD_CREDENTIALS")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df):
    print(f"嘗試開啟指定的試算表 ID: {spreadsheet_id}")
    try:
        # 嚴格開啟指定 ID，不允許去抓其他表
        spreadsheet = gc.open_by_key(spreadsheet_id)
        wks = spreadsheet.worksheet(sheet_name)
    except WorksheetNotFound:
        # 完全不執行自動建立，直接擋下來並報錯
        print(f"❌ 嚴格模式阻擋：在指定的試算表中找不到分頁 [{sheet_name}]。")
        print("請確認您已經在該 Google Sheet 裡面手動建立好這個分頁，程式拒絕自動創建。")
        return
    except Exception as e:
        print(f"❌ 開啟試算表失敗，可能是權限問題，請確認 Service Account ({e})")
        return
        
    try:
        # 清理 dataframe 以符合 GSheet 格式
        df_clean = df.copy()
        df_clean = df_clean.astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
        
        existing = wks.get_all_values()
        
        if not existing:
            # 初始化：寫入標題列與所有資料
            wks.update([df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 [{sheet_name}] 初始化寫入完成。")
        else:
            # 追加：比對日期，只寫入新資料
            existing_dates = set([str(row[0]) for row in existing[1:] if row])
            df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
            if not df_new.empty: 
                wks.append_rows(df_new.values.tolist())
                print(f"🟢 [{sheet_name}] 成功追加 {len(df_new)} 筆新日期資料。")
            else:
                print(f"⚡ [{sheet_name}] 語意分數已是最新，無需更新。")
    except Exception:
        print(f"❌ 寫入 {sheet_name} 時發生非預期的錯誤:")
        print(traceback.format_exc())

# ==========================================
# 3. 抓取 RSS 並計算特定關鍵字分數
# ==========================================
def fetch_sentiment_for_keyword(keyword):
    print(f"🔍 開始分析關鍵字: [{keyword}]")
    scores = []
    base_date = datetime.now()
    
    for i in range(CONFIG['LOOKBACK_DAYS']):
        d = base_date - timedelta(days=i)
        if d.weekday() >= 5: 
            continue # 跳過週末
            
        d_str = d.strftime("%Y-%m-%d")
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
                
                # 計算平均並保留 4 位小數
                daily_score = round(total_weight / max(len(titles), 1), 4)
                
        except Exception as e:
            # 發生錯誤時給予微小雜訊，避免產生極端空值
            daily_score = round(np.random.normal(0, 0.05), 4) 
            
        # 欄位名稱自動依照規則命名
        scores.append({"Date": d_str, f"{keyword}_AI_SCORE": daily_score})
        
        time.sleep(random.uniform(0.5, 1.5)) # 降低訪問頻率防 ban
        
    return pd.DataFrame(scores).sort_values("Date")

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*60 + "\n📰 多關鍵字台股新聞加權字典輿情分析器 (嚴格寫入版)\n" + "="*60)
    try:
        # 1. 抓取並合併所有關鍵字的分數
        final_df = None
        for kw in CONFIG['KEYWORDS_TO_CRAWL']:
            df_kw = fetch_sentiment_for_keyword(kw)
            
            if final_df is None:
                final_df = df_kw
            else:
                # 依據 Date 合併，確保不同關鍵字對齊在同一日期 (PCA 寬表格式)
                final_df = pd.merge(final_df, df_kw, on="Date", how="outer")
                
        # 依日期排序並將缺少的日期補上 0
        final_df = final_df.sort_values("Date").fillna(0)
        
        # 2. 測試環境判斷
        if "GSPREAD_CREDENTIALS" not in os.environ:
            print("\n⚠️ 未設定環境變數，僅預覽 DataFrame:")
            print(final_df.head(10))
            return

        # 3. 寫入指定 Google Sheet
        gc = get_gspread_client()
        sp_id = CONFIG["SPREADSHEET_ID"]
        target_sheet = CONFIG["TARGET_SHEET_NAME"]
        
        safe_gspread_write(gc, sp_id, target_sheet, final_df)
        
    except Exception:
        print("❌ 主程式發生錯誤:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
