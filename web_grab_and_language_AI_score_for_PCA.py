import os
import sys
import time
import random
import urllib.parse
import xml.etree.ElementTree as ET
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 機器學習與統計套件
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

# Google Sheets API 相關套件
try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("⚠️ 偵測到缺少必要套件。")
    print("請在終端機執行: pip install gspread google-auth pandas numpy requests scikit-learn")
    sys.exit(1)

# =====================================================================
# 🛠️ 系統全域組態設定區 (v5.0 整合版)
# =====================================================================
CONFIG = {
    # 1. 爬蟲與回溯設定
    "CRAWL_KEYWORD": "台股",         # 爬取新聞的關鍵字
    "START_DATE": "2026-01-01",     # 輿情分析回溯起點
    "CONSECUTIVE_LIMIT": 10,        # 連續失敗中斷閾值（防阻擋安全鎖）
    
    # 2. Google Sheets 設定
    "SPREADSHEET_NAME": "台股量化預測系統_v5", # Google 試算表名稱
    "CREDENTIALS_FILE": "google_service_account.json", # 金鑰 JSON 檔案路徑
    
    # 3. 本地中文財經情緒詞庫（免 API，高速、免付費、高抗阻擋）
    "BULLISH_WORDS": [
        "上漲", "大漲", "暴漲", "創高", "新高", "買超", "利多", "看旺", "強勢", 
        "多頭", "成長", "暴增", "翻倍", "反彈", "大好", "飆升", "噴出", "淨流入", 
        "旺季", "樂觀", "追捧", "擴產", "達標", "優於預期", "營收亮眼", "突破"
    ],
    "BEARISH_WORDS": [
        "下跌", "大跌", "暴跌", "重挫", "新低", "賣超", "利空", "看淡", "弱勢", 
        "空頭", "衰退", "虧損", "腰斬", "修正", "跌破", "縮水", "淨流出", "淡季", 
        "警訊", "悲觀", "賣壓", "砍單", "面臨考驗", "低於預期", "裁員", "調降"
    ]
}

# =====================================================================
# 🛡️ 模組一：Google News RSS 抗阻擋爬蟲 & 本地語意分析
# =====================================================================
class RSSNewsSentimentScraper:
    def __init__(self):
        # 模擬常見的瀏覽器 User-Agent，降低被 Google 阻擋的機率
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0"
        ]
        self.consecutive_failures = 0 # 連續失敗計數器

    def _get_headers(self):
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def fetch_daily_news_titles(self, target_date_str):
        """
        利用 Google News RSS 搜尋特定日期的關鍵字新聞。
        透過 after 和 before 語法精準鎖定單日新聞區間。
        """
        # 計算下一天以設定區間
        current_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        next_date = current_date + timedelta(days=1)
        next_date_str = next_date.strftime("%Y-%m-%d")
        
        # 構造 Google News RSS Date Filter 查詢詞 (例如: "台股 after:2026-01-01 before:2026-01-02")
        query = f"{CONFIG['CRAWL_KEYWORD']} after:{target_date_str} before:{next_date_str}"
        encoded_query = urllib.parse.quote(query)
        
        # Google News RSS 專用結構化 URL（阻擋率極低）
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        try:
            # 隨機延遲 1~3 秒，模擬人為正常瀏覽行為，避免觸發 IP 保護
            time.sleep(random.uniform(1.0, 3.0))
            
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            
            if response.status_code != 200:
                raise Exception(f"HTTP 連線異常，狀態碼: {response.status_code}")
                
            # 解析 RSS XML 檔案
            root = ET.fromstring(response.content)
            titles = []
            for item in root.findall(".//item"):
                title_elem = item.find("title")
                if title_elem is not None:
                    raw_title = title_elem.text
                    # 清理標題，去除來源尾綴（例如 "- 自由時報"）
                    clean_title = raw_title.split(" - ")[0] if " - " in raw_title else raw_title
                    titles.append(clean_title)
            
            # 只要成功連線解析，即歸零連續失敗計數
            self.consecutive_failures = 0
            return titles

        except Exception as e:
            self.consecutive_failures += 1
            print(f"\n❌ [異常資訊] 爬取 {target_date_str} 失敗！連續失敗次數: ({self.consecutive_failures}/{CONFIG['CONSECUTIVE_LIMIT']})")
            print(f"   失敗原因: {str(e)}")
            
            # 安全防線：當連續失敗次數達到 10 次，代表可能 IP 已被封鎖或發生嚴重網路問題，立即中斷程式並報警
            if self.consecutive_failures >= CONFIG['CONSECUTIVE_LIMIT']:
                print("\n🔥 [致命錯誤] 偵測到爬蟲連續失敗已達 10 次！可能已被 Google 阻擋或網路異常。")
                print("   為保護帳號與系統安全，程式將立即中斷並發出警訊。請檢查本地 IP 與網路狀態。")
                sys.exit(1) # 硬中斷退出
                
            return None

    def analyze_sentiment(self, titles):
        """
        本地端中文財經語意分析引擎 (免 API 消耗，極速運作)
        原理：計算利多與利空關鍵字的出現頻率，並計算歸一化情緒指標 (-1.0 至 1.0)
        """
        if not titles:
            return 0.0 # 當天無新聞，判定為情緒中立
            
        total_bullish = 0
        total_bearish = 0
        
        for title in titles:
            # 統計該標題內含的利多與利空詞彙數
            bullish_count = sum(1 for word in CONFIG["BULLISH_WORDS"] if word in title)
            bearish_count = sum(1 for word in CONFIG["BEARISH_WORDS"] if word in title)
            
            total_bullish += bullish_count
            total_bearish += bearish_count
            
        total_words = total_bullish + total_bearish
        if total_words == 0:
            return 0.0 # 若無匹配到任何情緒詞，判定為中立
            
        # 歸一化情緒公式: (利多 - 利空) / (利多 + 利空)
        score = (total_bullish - total_bearish) / total_words
        
        # 信心加權：若當天新聞太少，分數將往 0.0 (中立) 收斂，以降低單一八卦新聞造成的偏差
        weight = min(len(titles) / 5.0, 1.0) 
        final_score = round(score * weight, 4)
        
        return final_score

# =====================================================================
# 📊 模組二：Google Sheets 直接寫入與讀取介面
# =====================================================================
class GoogleSheetsConnector:
    def __init__(self):
        self.gc = None
        self.sheet = None
        self.connect()

    def connect(self):
        """
        利用您的 Google Drive 權限服務帳號金鑰，自動登入雲端硬碟並存取/新建試算表
        """
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        try:
            # 優先讀取本地 JSON 檔案，若是在 GitHub 則讀取環境變數中的 Secret
            if os.path.exists(CONFIG["CREDENTIALS_FILE"]):
                creds = Credentials.from_service_account_file(CONFIG["CREDENTIALS_FILE"], scopes=scopes)
            elif "GCP_SERVICE_ACCOUNT_JSON" in os.environ:
                import json
                info = json.loads(os.environ["GCP_SERVICE_ACCOUNT_JSON"])
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            else:
                print("⚠️ [提示] 未檢測到 Google 服務金鑰 (google_service_account.json)。")
                print("   系統將自動切換為『本地備份 CSV 模式』，仍可正常執行！")
                return False

            self.gc = gspread.authorize(creds)
            
            # 開啟指定的試算表
            try:
                self.sheet = self.gc.open(CONFIG["SPREADSHEET_NAME"])
            except gspread.exceptions.SpreadsheetNotFound:
                # 權限開通後，若找不到該名稱的 Sheet，程式會自動幫您在雲端建立一個！
                print(f"✨ 在您的 Google 雲端硬碟中新建試算表: {CONFIG['SPREADSHEET_NAME']}...")
                self.sheet = self.gc.create(CONFIG["SPREADSHEET_NAME"])
                # 建立主特徵與預測分頁
                self.sheet.add_worksheet(title="PCA_Features", rows="1000", cols="10")
                self.sheet.add_worksheet(title="Predict_Reports", rows="100", cols="10")
                try:
                    default_sheet = self.sheet.get_worksheet(0)
                    self.sheet.del_worksheet(default_sheet)
                except:
                    pass
            return True
        except Exception as e:
            print(f"❌ Google Sheets 連線失敗: {str(e)}")
            return False

    def is_active(self):
        return self.gc is not None and self.sheet is not None

    def read_features(self):
        """從 Google Sheet 讀取目前的特徵資料"""
        if self.is_active():
            try:
                wks = self.sheet.worksheet("PCA_Features")
                data = wks.get_all_records()
                if data:
                    df = pd.DataFrame(data)
                    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
                    return df
            except Exception as e:
                print(f"⚠️ 從 Google Sheet 讀取特徵失敗，改採本地備份: {str(e)}")
        
        # 離線備份讀取
        if os.path.exists("data/pca_features_backup.csv"):
            df = pd.read_csv("data/pca_features_backup.csv")
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            return df
        return None

    def write_features(self, df):
        """將合併了 X4 輿情分數的新特徵表寫回 Google Sheet 並更新本地備份"""
        df_sorted = df.sort_values(by="Date", ascending=True)
        
        # 儲存一份本地備份 CSV
        os.makedirs("data", exist_ok=True)
        df_sorted.to_csv("data/pca_features_backup.csv", index=False)
        
        if self.is_active():
            try:
                wks = self.sheet.worksheet("PCA_Features")
                wks.clear()
                # 轉換為 gspread 支援的二維陣列格式 (Header + Values)
                data_to_write = [df_sorted.columns.values.tolist()] + df_sorted.fillna("").values.tolist()
                wks.update("A1", data_to_write)
                print("🟢 已成功將更新後的特徵同步寫入至 Google Sheet [PCA_Features]！")
            except Exception as e:
                print(f"❌ 寫入 Google Sheet 特徵表失敗: {str(e)}")

    def write_predictions(self, df_report):
        """寫入最新的 PCA 預測訊號報告分頁"""
        if self.is_active():
            try:
                wks = self.sheet.worksheet("Predict_Reports")
                wks.clear()
                data_to_write = [df_report.columns.values.tolist()] + df_report.fillna("").values.tolist()
                wks.update("A1", data_to_write)
                print("🟢 已成功將 PCA 預測報告更新至 Google Sheet [Predict_Reports]！")
            except Exception as e:
                print(f"❌ 寫入預測報告失敗: {str(e)}")
        df_report.to_csv("data/pca_predictions_backup.csv", index=False)

# =====================================================================
# 📈 模組三：核心特徵處理、PCA 降維與 Ridge 預測
# =====================================================================
def run_pca_and_predict(df_features):
    """
    1. 特徵處理：對 2026/01/01 以前的缺失情緒值 (X4) 自動以 0.0 (中立) 填充，解決特徵長度不一問題。
    2. 將 X1, X2, X3, X4 四個維度的資料利用 PCA 降維至 2 個主成分。
    3. 藉由 Ridge 迴歸演算法計算未來的預期收益率，生成交易信號。
    """
    print("\n🔮 正在執行核心 PCA 降維與機器學習預測...")
    
    df_model = df_features.copy()
    
    # 【關鍵步驟】特徵填補：若 X4 欄位不存在則創建，並將 NaN / 缺失值全部填為 0.0 (中立)
    if 'X4' not in df_model.columns:
        df_model['X4'] = 0.0
    df_model['X4'] = df_model['X4'].fillna(0.0)
    
    # 確保特徵欄位齊全
    features_list = ['X1', 'X2', 'X3', 'X4']
    for col in features_list:
        if col not in df_model.columns:
            df_model[col] = 0.0
            
    # 若原本沒有目標回報欄位 (Target_Return)，則模擬一個與特徵相關的目標供模型學習 (實務上應綁定您的大盤數據)
    if 'Target_Return' not in df_model.columns:
        df_model['Target_Return'] = (
            df_model['X1']*0.25 - df_model['X2']*0.15 + df_model['X4']*0.4 + np.random.normal(0, 0.01, len(df_model))
        )
        
    X = df_model[features_list].values
    y = df_model['Target_Return'].values
    
    # 執行 PCA 降維，將 4 維資料壓縮成 2 個共線性極低的主成分
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X)
    
    # 訓練 Ridge 模型
    model = Ridge(alpha=1.0)
    model.fit(X_pca, y)
    
    # 進行預測
    y_pred = model.predict(X_pca)
    
    # 統合生成詳細報告
    df_report = pd.DataFrame({
        "Date": df_model["Date"],
        "X1_Technical": df_model["X1"],
        "X2_Capital": df_model["X2"],
        "X3_Macro": df_model["X3"],
        "X4_Sentiment": df_model["X4"],
        "PCA_Component_1": X_pca[:, 0],
        "PCA_Component_2": X_pca[:, 1],
        "Predicted_Return": y_pred
    })
    
    # 基於預測收益率給予直觀的交易訊號
    df_report['Signal'] = df_report['Predicted_Return'].apply(
        lambda x: "🟢 偏多 (BUY)" if x > 0.005 else ("🔴 偏空 (SELL)" if x < -0.005 else "🟡 觀望 (HOLD)")
    )
    
    # 列印 PCA 變異數解釋比率
    explained_var = pca.explained_variance_ratio_
    print(f"📊 PCA 降維完成。主成分 1 解釋度: {explained_var[0]:.2%}, 主成分 2 解釋度: {explained_var[1]:.2%}")
    print(f"🎯 今日最新預測訊號: {df_report.iloc[-1]['Signal']} (預估回報: {df_report.iloc[-1]['Predicted_Return']:.4%})")
    
    return df_report

# =====================================================================
# 🚀 系統自動化主運行流程
# =====================================================================
def main():
    print("=====================================================")
    print("📈 台股量化預測系統 v5.0 - 主控與 PCA 整合管線啟動 🚀")
    print("=====================================================")
    
    # 1. 建立 Google Sheets 連接
    sheets = GoogleSheetsConnector()
    
    # 2. 獲取當前特徵資料表
    df_features = sheets.read_features()
    
    # 如果全新啟動且無歷史備份，自動建立基本特徵表
    if df_features is None:
        print("💡 檢測為初次運行，自動初始化 2025/01/01 至今的基礎特徵陣列 (X1, X2, X3)...")
        base_start = datetime(2025, 1, 1)
        today = datetime.now()
        dates = [(base_start + timedelta(days=x)).strftime("%Y-%m-%d") for x in range((today - base_start).days + 1)]
        
        df_features = pd.DataFrame({
            "Date": dates,
            "X1": np.sin(np.arange(len(dates)) / 12.0) * 0.4 + np.random.normal(0, 0.08, len(dates)),
            "X2": np.cos(np.arange(len(dates)) / 18.0) * 0.2 + np.random.normal(0, 0.04, len(dates)),
            "X3": np.random.normal(0, 0.8, len(dates)),
            "X4": np.nan # 待爬蟲模組填充的空特徵
        })
    
    # 3. 比對並搜尋需要回溯/補件的新聞日期 (自 2026-01-01 起至今天)
    start_dt = datetime.strptime(CONFIG["START_DATE"], "%Y-%m-%d")
    today_dt = datetime.now()
    
    df_features['Date_parsed'] = pd.to_datetime(df_features['Date'])
    
    # 篩選出 2026-01-01 之後、目前在資料庫中為空值或 0.0 需要更新的日期
    target_df = df_features[
        (df_features['Date_parsed'] >= start_dt) & 
        (df_features['Date_parsed'] <= today_dt) & 
        (df_features['X4'].isna() | (df_features['X4'] == 0.0))
    ]
    
    dates_to_crawl = target_df['Date'].tolist()
    df_features = df_features.drop(columns=['Date_parsed']) # 移除暫時的解析欄位
    
    if not dates_to_crawl:
        print("🎉 2026/01/01 至今的 X4 輿情特徵均已補齊，不需啟動爬蟲模組。")
    else:
        print(f"📅 偵測到共有 {len(dates_to_crawl)} 天的 X4 輿情數據需要回溯補件...")
        
        # 實例化新聞爬蟲
        scraper = RSSNewsSentimentScraper()
        
        # 逐日開始爬取並填充特徵
        for idx, target_date in enumerate(dates_to_crawl):
            print(f"🕒 [{idx+1}/{len(dates_to_crawl)}] 正在獲取 {target_date} 新聞資訊...", end="")
            
            # 呼叫 RSS 爬蟲
            titles = scraper.fetch_daily_news_titles(target_date)
            
            if titles is not None:
                # 本地語意分析計分
                score = scraper.analyze_sentiment(titles)
                
                # 回填至特徵表
                row_idx = df_features[df_features['Date'] == target_date].index
                if len(row_idx) > 0:
                    df_features.at[row_idx[0], 'X4'] = score
                print(f" 成功！取得標題 {len(titles)} 條，本地情緒分數 X4 = {score}")
            else:
                print(" 失敗，跳過該日。")
                
            # 每累積 5 天自動向雲端存檔一次，防意外中斷
            if idx % 5 == 0 and idx > 0:
                sheets.write_features(df_features)
                
        # 爬取完成，全量寫入 Google Sheets / 備份
        sheets.write_features(df_features)

    # 4. 運行 PCA 特徵壓縮與 Ridge 迴歸
    df_report = run_pca_and_predict(df_features)
    
    # 5. 將最新預測結果輸出至雲端 Predict_Reports 工作表
    sheets.write_predictions(df_report)
    print("\n🏁 系統 v5.0 管線自動化執行完成！請至您的 Google Sheet 檢查對齊後的資料。")

if __name__ == "__main__":
    main()
