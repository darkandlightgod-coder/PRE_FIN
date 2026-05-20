# -*- coding: utf-8 -*-
"""
V14.0 PCA_Master_Exceed 整合版
- 將籌碼資料抓取與價格資料處理整併為單一檔案
- 使用 pd.merge 實現資料合併呈現
"""

import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import time
import random

# 【整合區塊：籌碼資料抓取邏輯】
def fetch_chip_data_integrated(stock_id):
    """直接在模組內處理籌碼資料，不需要額外檔案"""
    try:
        # 此處為範例連結，請根據您實際抓取的網站 API 調整
        url = f"https://example.com/api/chips/{stock_id}"
        response = requests.get(url, timeout=10)
        data = response.json()
        return pd.DataFrame(data)
    except Exception as e:
        print(f"⚠️ 籌碼資料抓取失敗 ({stock_id}): {e}")
        return pd.DataFrame()

# 【核心合併邏輯：整合進既有的 update_master_dataset】
def update_master_dataset(gc):
    print("🚀 開始進行價格與籌碼資料合併...")
    
    # 1. 抓取價格資料 (原有邏輯)
    price_df = get_price_data_from_yfinance() 
    
    # 2. 抓取籌碼資料 (直接於此整合)
    all_chips = []
    stock_list = ["2330", "2303"] # 您的個股清單
    for sid in stock_list:
        chip = fetch_chip_data_integrated(sid)
        all_chips.append(chip)
        time.sleep(random.uniform(1, 2))
        
    chips_df = pd.concat(all_chips)
    
    # 3. 進行整併 (以日期與代號合併)
    final_df = pd.merge(price_df, chips_df, on=["Date", "Stock"], how="left")
    
    # 4. 統計填補與清洗 (確保整張表完整)
    final_df = final_df.fillna(0)
    
    print("✅ 整合完成，現已納入統計與預測循環中")
    return final_df

# ... 原有的 main() 與其他分析邏輯保持不變 ...
