# -*- coding: utf-8 -*-
"""
V14.1.1 光速批次更新器 (Pandas 向量極速防呆版)
優化重點：
1. 捨棄緩慢的 Python 字典雙重迴圈補值。
2. 採用 Pandas combine_first 進行矩陣級別的資料融合，速度提升百倍。
3. 批次下載後直接處理 MultiIndex，完全向量化運算。
4. 🚀 導入無敵防呆裝甲：自動修復表頭空白、中英文異動，表單全空時自動啟動防護不當機。
"""
import os
import json
import time
import pandas as pd
import numpy as np
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
PERIOD = "1mo"  # 每日更新抓近1個月

def get_tickers_from_headers(headers):
    """掃描表頭，提取所有的基礎股票代號 (不含 .TW)"""
    tickers = set()
    for header in headers:
        if header.endswith("_Close") or header.endswith("_Volume"):
            ticker = header.split('_')[0]
            tickers.add(ticker)
    return sorted(list(tickers))

def fetch_and_flatten_yf_data(tickers_with_suffix, period):
    """批次下載並將 Yahoo 的 MultiIndex 扁平化為我們需要的格式 (例如: 2330_Close)"""
    if not tickers_with_suffix: return pd.DataFrame()
    
    df = yf.download(tickers_with_suffix, period=period, threads=True, progress=False)
    if df.empty: return pd.DataFrame()

    # 處理 MultiIndex 欄位 (yfinance 新版回傳格式)
    if isinstance(df.columns, pd.MultiIndex):
        flat_cols = []
        valid_cols = []
        for col in df.columns:
            if col[0] in ['Close', 'Volume']:
                flat_cols.append(f"{col[1]}_{col[0]}")
                valid_cols.append(col)
        
        df = df[valid_cols]
        df.columns = flat_cols
    else:
        # 單一標的時不會是 MultiIndex
        df = df[['Close', 'Volume']]
        df.columns = [f"{tickers_with_suffix[0]}_Close", f"{tickers_with_suffix[0]}_Volume"]

    # 確保 Index 是 datetime 且沒有時區
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

def main():
    print("="*60)
    print("⚡ 啟動光速批次更新器 (Pandas 向量極速防呆版)")
    print("="*60)

    # ------------------------------------------------
    # 1. 連線 Google Sheet
    # ------------------------------------------------
    print("☁️ 階段一：讀取 Google Sheet 現有資料庫...")
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        print("❌ 找不到 GSPREAD_CREDENTIALS 環境變數。")
        return
        
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
    gc = gspread.authorize(credentials)
    
    try:
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ 找不到試算表 {SHEET_NAME}！")
        return

    # ✅ V14.1.1 強化防呆版：讀取雲端表單
    all_values = worksheet.get_all_values()
    headers = []
    tickers_to_fetch = []
    
    # 🛡️ 防護 1：如果表單完全是空的（被清空或初次建立）
    if not all_values or not all_values[0]:
        print("   ⚠️ 雲端表單目前為空，系統將跳過歷史讀取，直接建立新資料庫...")
        df_cloud = pd.DataFrame()
    else:
        # 🛡️ 防護 2：清除表頭可能存在的隱形空白字元
        headers = [str(h).strip() for h in all_values[0]]
        df_cloud = pd.DataFrame(all_values[1:], columns=headers)
        
        # 🛡️ 防護 3：智慧辨識並修復日期欄位
        if 'Date' not in df_cloud.columns:
            if '日期' in df_cloud.columns:
                df_cloud.rename(columns={'日期': 'Date'}, inplace=True)
                print("   ⚠️ [自動修復] 將 '日期' 轉換為 'Date'")
            elif len(df_cloud.columns) > 0:
                original_first_col = df_cloud.columns[0]
                df_cloud.rename(columns={original_first_col: 'Date'}, inplace=True)
                print(f"   ⚠️ [自動修復] 強制將第一欄 '{original_first_col}' 設為 'Date'")
                
        # 🛡️ 防護 4：確保 Date 轉型成功並設定為 Index
        if 'Date' in df_cloud.columns:
            df_cloud['Date'] = pd.to_datetime(df_cloud['Date'], errors='coerce')
            df_cloud.dropna(subset=['Date'], inplace=True)
            df_cloud.set_index('Date', inplace=True)
            
            # 從整理好的表頭提取要抓的代碼
            tickers_to_fetch = get_tickers_from_headers(headers)
        else:
            print("   ❌ [致命錯誤] 表頭結構完全損毀，視為空表單重新建立。")
            df_cloud = pd.DataFrame()

    if not df_cloud.empty:
        df_cloud = df_cloud.replace("", np.nan).apply(pd.to_numeric, errors='coerce')

    # ------------------------------------------------
    # 2. 爬取最新資料 (Yahoo Finance)
    # ------------------------------------------------
    print(f"\n📡 階段二：向 Yahoo Finance 批次請求 {len(tickers_to_fetch)} 檔標的最新資料...")
    if not tickers_to_fetch:
        print("   ⚠️ 雲端表單內未偵測到任何有效的標的代號欄位 (如 TX=F_Close)，程式結束。")
        return
        
    df_new = fetch_and_flatten_yf_data(tickers_to_fetch, PERIOD)
    if df_new.empty:
        print("   ❌ 無法獲取任何新資料，程式結束。")
        return
    print(f"   ✅ 成功下載 {len(df_new)} 筆最新交易日資料。")

    # ------------------------------------------------
    # 3. 矩陣融合 (Pandas combine_first 魔法)
    # ------------------------------------------------
    print("\n🧠 階段三：啟動 Pandas 矩陣融合 (補缺漏值)...")
    close_cols = [c for c in df_new.columns if c.endswith("_Close")]
    vol_cols = [c for c in df_new.columns if c.endswith("_Volume")]
    df_new[close_cols] = df_new[close_cols].round(2)
    
    if not df_cloud.empty:
        df_final = df_new.combine_first(df_cloud)
    else:
        df_final = df_new.copy()
        
    df_final.sort_index(inplace=True)

    # ------------------------------------------------
    # 4. 格式化與寫回 Google Sheet
    # ------------------------------------------------
    print("\n🔄 階段四：格式化並整包覆蓋寫回 Google Sheet...")
    df_final.reset_index(inplace=True)
    df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
    
    # 🛡️ 防護 5：確保寫回的表頭順序與原本一致 (如果原本有表頭的話)
    if headers and 'Date' in headers:
        ordered_cols = ['Date'] + [col for col in headers if col in df_final.columns and col != 'Date']
        # 加入新抓到但原本表單沒有的欄位
        new_cols = [col for col in df_final.columns if col not in ordered_cols]
        df_final = df_final[ordered_cols + new_cols]
    
    # 格式化輸出
    for col in df_final.columns:
        if col.endswith("_Volume"):
            df_final[col] = df_final[col].apply(lambda x: int(x) if pd.notna(x) and str(x).strip() != "" else "")
            
    df_final = df_final.replace([np.inf, -np.inf], np.nan).fillna("")
    
    output_data = [df_final.columns.tolist()] + df_final.values.tolist()
    
    worksheet.clear()
    worksheet.update(values=output_data, range_name=None)
    print(f"🎉 更新成功！目前總資料庫共 {len(df_final)} 筆，已全數寫入。")

if __name__ == "__main__":
    main()
