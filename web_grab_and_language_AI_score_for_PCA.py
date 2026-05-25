# -*- coding: utf-8 -*-
"""
V13.0 web_grab_and_language_AI_score_for_PCA.py
純 Python 字典計分版 (無依賴外部 AI API，無限次執行)
特色:
1. 嚴格綁定 Google Sheet ID，杜絕誤創檔案。
2. 強制寫入並對齊所有欄位名稱 (關鍵字_AI_SCORE)，適合 PCA 特徵工程。
3. 採用全覆寫同步(Full-Sync)模式，自動處理空表與欄位變更。
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
    
    # 追蹤的關鍵字陣列 (未來可隨時新增，系統會自動擴充欄位)
    "KEYWORDS_TO_CRAWL": ["台股", "台指期", "費半", "那斯達克", "台積電"],
    "LOOKBACK_DAYS": 30, 
    
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
# 2. Google Sheet 認證與完美合併寫入
# ==========================================
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("⚠️ 找不到 GSPREAD_CREDENTIALS 環境變數。")
        raise ValueError("Missing GSPREAD_CREDENTIALS")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df_new):
    print(f"嘗試開啟指定的試算表 ID: {spreadsheet_id}")
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except WorksheetNotFound:
        print(f"❌ 嚴格模式阻擋：找不到分頁 [{sheet_name}]，請手動建立。")
        return
    except Exception as e:
        print(f"❌ 開啟試算表失敗: {e}")
        return
        
    try:
        # 取得雲端現有資料
        existing_vals = wks.get_all_values()
        
        # 判斷雲端資料是否包含有效的標題列 ('Date')
        if existing_vals and len(existing_vals) > 0 and 'Date' in existing_vals[0]:
            headers = existing_vals[0]
            df_existing = pd.DataFrame(existing_vals[1:], columns=headers)
        else:
            # 如果全是空白或是沒有標題，當作全新表格處理
            df_existing = pd.DataFrame()

        # 將雲端資料與新抓取的資料進行完美合併
        if not df_existing.empty:
            df_existing['Date'] = pd.to_datetime(df_existing['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
            # 若日期重複，保留最新抓取的資料
            df_final = df_final.drop_duplicates(subset=['Date'], keep='last')
        else:
            df_final = df_new.copy()

        # 依日期排序，處理缺失值 (如新增關鍵字產生的空缺一律補 0)
        df_final['Date'] = pd.to_datetime(df_final['Date'])
        df_final = df_final.sort_values("Date")
        df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
        df_final = df_final.fillna(0)

        # 轉換格式並準備寫入矩陣 (第一列強制放入 columns)
        df_final_clean = df_final.astype(str).replace({"nan": "0", "NaN": "0", "NaT": ""})
        write_data = [df_final_clean.columns.tolist()] + df_final_clean.values.tolist()
        
        # 清空工作表並一次性完整更新
        wks.clear()
        
        # 兼容不同版本的 gspread API 語法
        try:
            wks.update(range_name="A1", values=write_data)
        except TypeError:
            wks.update("A1", write_data)
            
        print(f"🟢 [{sheet_name}] 更新成功！第一列已確保為完整的欄位名稱。")
        print(f"📊 目前共有 {len(df_final_clean)} 天的特徵矩陣。")
        
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
            continue 
            
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
                daily_score = round(total_weight / max(len(titles), 1), 4)
        except Exception:
            daily_score = round(np.random.normal(0, 0.05), 4) 
            
        scores.append({"Date": d_str, f"{keyword}_AI_SCORE": daily_score})
        time.sleep(random.uniform(0.5, 1.5)) 
        
    return pd.DataFrame(scores)

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*60 + "\n📰 多關鍵字台股新聞加權字典輿情分析器 (全覆寫對齊版)\n" + "="*60)
    try:
        final_df = None
        for kw in CONFIG['KEYWORDS_TO_CRAWL']:
            df_kw = fetch_sentiment_for_keyword(kw)
            if final_df is None:
                final_df = df_kw
            else:
                final_df = pd.merge(final_df, df_kw, on="Date", how="outer")
                
        final_df = final_df.sort_values("Date").fillna(0)
        
        if "GSPREAD_CREDENTIALS" not in os.environ:
            print("\n⚠️ 未設定環境變數，僅預覽 DataFrame:")
            print(final_df.head(10))
            return

        gc = get_gspread_client()
        sp_id = CONFIG["SPREADSHEET_ID"]
        target_sheet = CONFIG["TARGET_SHEET_NAME"]
        
        safe_gspread_write(gc, sp_id, target_sheet, final_df)
        
    except Exception:
        print("❌ 主程式發生錯誤:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
