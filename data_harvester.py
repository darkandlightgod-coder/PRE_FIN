# -*- coding: utf-8 -*-
"""
V1.0 台股籌碼資料採集與整合器
=========================================================
功能:
1. 從公開來源獲取個股籌碼數據 (融資券/董監持股)
2. 自動處理重試與空值防呆 (Backfill)
3. 整合至 Google Sheet: specific_stock_goods_data
"""

import requests
import pandas as pd
import time
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class StockHarvester:
    def __init__(self, gc):
        self.gc = gc
        self.session = self._create_session()
        self.target_sheet = "specific_stock_goods_data"

    def _create_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        return session

    def fetch_chip_data(self, stock_id):
        """爬取個股籌碼範例 (需根據實際 URL 調整)"""
        print(f"🔍 正在爬取 {stock_id} 籌碼資訊...")
        try:
            # 模擬請求目標網站
            url = f"https://api.cnyes.com/v1/stock/chips/{stock_id}"
            response = self.session.get(url, timeout=10)
            data = response.json()
            
            # 防呆：檢查是否為空
            if not data or 'data' not in data:
                return {"Date": pd.Timestamp.now().strftime('%Y-%m-%d'), "Stock": stock_id, "Margin": 0, "Holdings": 0}
            
            return {
                "Date": pd.Timestamp.now().strftime('%Y-%m-%d'),
                "Stock": stock_id,
                "Margin": data.get('margin_rate', 0), # 若無資料自動補 0
                "Holdings": data.get('director_holdings', 0)
            }
        except Exception as e:
            print(f"⚠️ 抓取 {stock_id} 失敗: {e}")
            return {"Date": pd.Timestamp.now().strftime('%Y-%m-%d'), "Stock": stock_id, "Margin": 0, "Holdings": 0}

    def update_master_sheet(self, new_data_list):
        """將新資料 rbind 進 Google Sheet"""
        sh = self.gc.open(self.target_sheet)
        wks = sh.sheet1
        
        # 1. 讀取舊資料
        all_records = wks.get_all_records()
        old_df = pd.DataFrame(all_records) if all_records else pd.DataFrame(columns=["Date", "Stock", "Margin", "Holdings"])
        
        # 2. 合併新舊資料
        new_df = pd.DataFrame(new_data_list)
        combined_df = pd.concat([old_df, new_df]).drop_duplicates(subset=['Date', 'Stock'], keep='last')
        
        # 3. 清空並寫回
        wks.clear()
        wks.append_row(combined_df.columns.tolist())
        wks.append_rows(combined_df.values.tolist())
        print(f"✅ 成功寫入 {len(new_data_list)} 筆新資料至 {self.target_sheet}")

# 使用範例：
# harvester = StockHarvester(gc)
# chips = [harvester.fetch_chip_data(s) for s in ["2330", "2303"]]
# harvester.update_master_sheet(chips)
