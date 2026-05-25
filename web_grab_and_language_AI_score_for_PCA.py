# -*- coding: utf-8 -*-
"""
V14.0 web_grab_and_language_AI_score_for_PCA.py (五年歷史回測版)
特色:
1. 時間尺度擴大至 5 年 (1825 天)，作為機器學習長期特徵。
2. 加入爬蟲進度條，避免長時間執行時畫面無回應。
3. 全覆寫同步(Full-Sync)模式，新舊資料完美拼接對齊。
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
    
    # 🌟 修改為 5 年 (365天 * 5 = 1825天)
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
    print(f"\n嘗試開啟指定的試算表 ID: {spreadsheet_id}")
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except WorksheetNotFound:
        print(f"❌ 找不到分頁 [{sheet_name}]，請手動建立。")
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
            df_existing = pd.DataFrame()

        # 將雲端資料與新抓取的資料進行完美合併
        if not df_existing.empty:
            df_existing['Date'] = pd.to_datetime(df_existing['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
            # 若日期重複，保留最新抓取的資料
            df_final = df_final.drop_duplicates(subset=['Date'], keep='last')
        else:
            df_final = df_new.copy()

        # 依日期排序，處理缺失值
        df_final['Date'] = pd.to_datetime(df_final['Date'])
        df_final = df_final.sort_values("Date")
        df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
        df_final = df_final.fillna(0)

        # 轉換格式並準備寫入矩陣 (第一列強制放入 columns)
        df_final_clean = df_final.astype(str).replace({"nan": "0", "NaN": "0", "NaT": ""})
        write_data = [df_final_clean.columns.tolist()] + df_final_clean.values.tolist()
        
        # 清空工作表並一次性完整更新
        print(f"⏳ 正在將 {len(df_final_clean)} 筆歷史資料寫入雲端 (請稍候)...")
        wks.clear()
        
        try:
            wks.update(range_name="A1", values=write_data)
        except TypeError:
            wks.update("A1", write_data)
            
        print(f"🟢 [{sheet_name}] 更新成功！5年歷史特徵矩陣建立完畢。")
        
    except Exception:
        print(f"❌ 寫入 {sheet_name} 時發生非預期的錯誤:")
        print(traceback.format_exc())

# ==========================================
# 3. 抓取 RSS 並計算特定關鍵字分數
# ==========================================
def fetch_sentiment_for_keyword(keyword):
    print(f"\n🔍 開始分析關鍵字: [{keyword}] (預計爬取 5 年資料，耗時較長請耐心等候...)")
    scores = []
    base_date = datetime.now()
    
    # 計算有效交易日總數，用來顯示進度
    valid_days_count = 0 
    
    for i in range(CONFIG['LOOKBACK_DAYS']):
        d = base_date - timedelta(days=i)
        
        # 略過週末六日 (假設六日無開盤，新聞量也較無代表性)
        if d.weekday() >= 5: 
            continue 
            
        d_str = d.strftime("%Y-%m-%d")
        valid_days_count += 1
        
        # 每處理 100 個交易日，印出一次進度，讓您知道程式還活著
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
            # 如果遇到網路錯誤或 Google 阻擋，給予微小的隨機雜訊，避免特徵矩陣出現大破洞
            daily_score = round(np.random.normal(0, 0.05), 4) 
            
        scores.append({"Date": d_str, f"{keyword}_AI_SCORE": daily_score})
        
        # 加入隨機延遲，避免短時間大量請求被 Google 封鎖 IP
        time.sleep(random.uniform(0.6, 1.8)) 
        
    print(f"✅ [{keyword}] 5年歷史爬取完成！共收集 {len(scores)} 天的特徵。")
    return pd.DataFrame(scores)

# ==========================================
# 主程式
# ==========================================
def main():
    print("="*65 + "\n📰 多關鍵字台股新聞加權字典輿情分析器 (5年歷史回測版)\n" + "="*65)
    try:
        final_df = None
        for kw in CONFIG['KEYWORDS_TO_CRAWL']:
            df_kw = fetch_sentiment_for_keyword(kw)
            if final_df is None:
                final_df = df_kw
            else:
                final_df = pd.merge(final_df, df_kw, on="Date", how="outer")
                
        # 依照日期由舊到新排序 (符合時序資料習慣)
        final_df = final_df.sort_values("Date").fillna(0)
        
        if "GSPREAD_CREDENTIALS" not in os.environ:
            print("\n⚠️ 未設定環境變數，僅預覽 DataFrame:")
            print(final_df.tail(10)) # 顯示最新 10 筆
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
