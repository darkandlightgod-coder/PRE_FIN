import os
import sys
import subprocess
import traceback
import asyncio
import random
import re
from datetime import datetime
import importlib
import json
import urllib.parse

# ==========================================
# 【1. 雲端自癒環境檢測】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 web_grab_and_language_AI_score_for_PCA V4.0 環境自檢...")
    dependencies = {
        "pandas": "pandas",
        "yfinance": "yfinance",
        "bs4": "beautifulsoup4",
        "playwright": "playwright",
        "nest_asyncio": "nest_asyncio",
        "requests": "requests",
        "snownlp": "snownlp",
        "vaderSentiment": "vaderSentiment",
        "gspread": "gspread",
        "oauth2client": "oauth2client"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 正在自動安裝缺失套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 輿情套件與語意引擎準備完畢。")
    
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True)
    except: pass

bootstrap()

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import nest_asyncio
import requests
from snownlp import SnowNLP
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import gspread
from oauth2client.service_account import ServiceAccountCredentials

nest_asyncio.apply()

# ==========================================
# 【2. 動態路徑與雲端設定對齊】
# ==========================================
BASE_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(BASE_DIR, exist_ok=True)
LOCAL_CSV_PATH = os.path.join(BASE_DIR, "stock_history.csv")

# Google Drive 試算表名稱對齊
CLOUD_SHEET_NAME = "stock_history"
HEADLESS_MODE = True

MAX_CONCURRENT_KEYWORDS = 2
MAX_CONCURRENT_ARTICLES = 2

# 🧱 輿情採集核心關鍵字
TIER1_KEYWORDS = ["台股 大盤"]
TIER2_KEYWORDS = ["Taiwan Stock Market Index", "費城半導體"]
TIER3_KEYWORDS = ["TSMC ADR stock news", "MSCI Taiwan Index"]

# ==========================================
# 【3. 雲端 Google Sheets 雙向同步模組】
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope))
        except Exception as e:
            print(f"⚠️ 解析 GSPREAD_CREDENTIALS 失敗: {e}")
            
    local_creds = "credentials.json"
    if os.path.exists(local_creds):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name(local_creds, scope))
        except: pass
    return None

def load_historical_舆情():
    gc = get_gspread_client()
    if gc:
        try:
            sh = gc.open(CLOUD_SHEET_NAME)
            records = sh.sheet1.get_all_records()
            if records:
                df = pd.DataFrame(records)
                print(f"☁️ [雲端載入] 成功自 Google Sheets 讀取 {len(df)} 筆歷史輿情資料。")
                return df
        except Exception as e:
            print(f"⚠️ 雲端輿情讀取失敗 (將由本地快取遞補): {e}")
            
    if os.path.exists(LOCAL_CSV_PATH):
        print(f"📂 [本地載入] 讀取本地輿情歷史快取: {LOCAL_CSV_PATH}")
        return pd.read_csv(LOCAL_CSV_PATH)
    return pd.DataFrame()

def save_and_sync_舆情(df):
    df = df.sort_values(by="Date").reset_index(drop=True)
    df.to_csv(LOCAL_CSV_PATH, index=False, encoding="utf-8-sig")
    
    gc = get_gspread_client()
    if gc:
        try:
            try:
                sh = gc.open(CLOUD_SHEET_NAME)
            except gspread.exceptions.SpreadsheetNotFound:
                sh = gc.create(CLOUD_SHEET_NAME)
            sheet = sh.sheet1
            sheet.clear()
            df_clean = df.fillna("")
            sheet.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
            print(f"🎉 [雲端同步] 成功覆蓋更新 Google Sheets '{CLOUD_SHEET_NAME}'，共 {len(df_clean)} 筆。")
        except Exception as e:
            print(f"❌ 雲端輿情同步失敗: {e}")

# ==========================================
# 【4. 數據採集與解析邏輯】
# ==========================================
async def get_market_indicators():
    results = {}
    try:
        tickers = {"TWII": "^TWII", "SOX": "^SOX"}
        for name, symbol in tickers.items():
            df = yf.download(symbol, period="7d", interval="1d", progress=False, auto_adjust=True)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                closes = df['Close'].squeeze()
                vols = df['Volume'].squeeze() if 'Volume' in df.columns else None
                
                val_last = float(closes.iloc[-1])
                val_prev = float(closes.iloc[-2])
                results[f"{name}_Change"] = ((val_last - val_prev) / val_prev) * 100
                
                if name == "TWII" and vols is not None:
                    vol_last = float(vols.iloc[-1])
                    vol_prev = float(vols.iloc[-2])
                    results["TWII_Vol_Change"] = ((vol_last - vol_prev) / vol_prev) * 100
    except Exception as e:
        print(f"⚠️ 市場大盤量價數據解析異常: {e}")
    return results

async def grab_news(days=1):
    print(f"\n🕵️ 啟動 Playwright 無頭新聞採集...")
    news_list = []
    processed_titles = set()
    tbs = "qdr:w" if days > 1 else "qdr:d"
    exclude_keywords = ["意見回饋", "隱私權", "說明", "Google", "服務條款", "下一頁", "上一頁"]
    
    sem_keyword = asyncio.Semaphore(MAX_CONCURRENT_KEYWORDS)
    sem_article = asyncio.Semaphore(MAX_CONCURRENT_ARTICLES)
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=HEADLESS_MODE)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            async def deep_read_article(title, art_url):
                async with sem_article:
                    try:
                        art_page = await context.new_page()
                        await art_page.goto(art_url, wait_until="domcontentloaded", timeout=12000)
                        art_html = await art_page.content()
                        art_soup = BeautifulSoup(art_html, 'html.parser')
                        p_tags = art_soup.find_all('p')
                        paragraphs = [p.get_text().strip() for p in p_tags if len(p.get_text().strip()) > 25]
                        content = "\n".join(paragraphs[:4]).strip()
                        await art_page.close()
                        return {"title": title, "content": content if content else title}
                    except:
                        try: await art_page.close()
                        except: pass
                        return {"title": title, "content": title}

            async def process_keyword(keyword):
                async with sem_keyword:
                    url = f"https://www.google.com/search?q={keyword}&tbm=nws&tbs={tbs}"
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        content = await page.content()
                        soup = BeautifulSoup(content, 'html.parser')
                        candidate_links = []
                        for a in soup.find_all('a'):
                            raw_href = a.get('href', '')
                            if not raw_href or "google.com" in raw_href or not raw_href.startswith('http'): continue
                            
                            h3 = a.find('h3')
                            title_text = h3.get_text().strip() if h3 else ""
                            if title_text and not any(ek in title_text for ek in exclude_keywords):
                                candidate_links.append((title_text, raw_href))
                        
                        await page.close()
                        valid_articles = []
                        for t, l in candidate_links:
                            if t not in processed_titles:
                                processed_titles.add(t)
                                valid_articles.append((t, l))
                            if len(valid_articles) >= 3: break
                        
                        if valid_articles:
                            sub_tasks = [deep_read_article(t, l) for t, l in valid_articles]
                            results = await asyncio.gather(*sub_tasks)
                            news_list.extend(results)
                    except Exception as e:
                        print(f"      ⚠️ 關鍵字 【{keyword}】 處理異常: {e}")
                        try: await page.close()
                        except: pass

            all_keywords = TIER1_KEYWORDS + TIER2_KEYWORDS + TIER3_KEYWORDS
            tasks = [process_keyword(kw) for kw in all_keywords]
            await asyncio.gather(*tasks)
            await browser.close()
        except Exception as e:
            print(f"❌ 新聞採集致命失敗: {e}")
    return news_list

# ==========================================
# 【5. 語意分析：純本地雙語分析引擎】
# ==========================================
def is_mainly_english(text):
    eng_chars = len(re.findall(r'[a-zA-Z]', text))
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return eng_chars > zh_chars

def analyze_sentiment_local_only(news_list):
    print(f"💻 啟動本地端雙語語意分析引擎 (SnowNLP 中文 + VADER 英文)...")
    news_scores = []
    total_score = 0.0
    vader_analyzer = SentimentIntensityAnalyzer()
    
    for item in news_list:
        title = item['title']
        content = item['content']
        target_text = content[:400] if content else title
        try:
            if is_mainly_english(target_text):
                vs = vader_analyzer.polarity_scores(target_text)
                mapped_score = vs['compound'] * 5.0
            else:
                s = SnowNLP(target_text)
                mapped_score = (s.sentiments - 0.5) * 10.0
                mapped_score = max(-5.0, min(5.0, mapped_score))
            
            news_scores.append({"title": title, "score": mapped_score})
            total_score += mapped_score
        except:
            news_scores.append({"title": title, "score": 0.0})
            
    overall_sentiment = total_score / len(news_list) if news_list else 0.0
    return {"news_scores": news_scores, "overall_sentiment": overall_sentiment}

# ==========================================
# 【6. 主執行流】
# ==========================================
async def main():
    print("="*60)
    print("🕵️ web_grab_and_language_AI_score_for_PCA V4.0 (線上化與純本地語意版)")
    print("="*60)
    
    df_old = load_historical_舆情()
    
    market_data = await get_market_indicators()
    days = 3 if datetime.now().weekday() == 0 else 1
    news_data = await grab_news(days=days)
    
    sentiment_result = {"overall_sentiment": 0.0}
    if news_data:
        sentiment_result = analyze_sentiment_local_only(news_data)
        
    x1 = market_data.get("TWII_Change", 0.0)
    x2 = market_data.get("TWII_Vol_Change", 0.0)
    x3 = market_data.get("SOX_Change", 0.0)
    x4 = sentiment_result.get("overall_sentiment", 0.0)
    
    today_str = datetime.now().strftime('%Y/%m/%d')
    engine_name = "Local_Bilingual"
    
    new_row = pd.DataFrame([{
        "Date": today_str,
        "X1_TWII_Change": round(x1, 6),
        "X2_TWII_Vol_Change": round(x2, 6),
        "X3_SOX_Change": round(x3, 6),
        "X4_Sentiment_Score": round(x4, 6),
        "NLP_Engine": engine_name
    }])
    
    df_final = pd.concat([df_old, new_row], ignore_index=True) if not df_old.empty else new_row
    df_final = df_final.drop_duplicates(subset=["Date"], keep="last")
    
    save_and_sync_舆情(df_final)

if __name__ == "__main__":
    asyncio.run(main())
