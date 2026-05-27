# -*- coding: utf-8 -*-
"""
V14.1 光速批次更新器 (Pandas 向量極速版)
優化重點：
1. 捨棄緩慢的 Python 字典雙重迴圈補值。
2. 採用 Pandas combine_first 進行矩陣級別的資料融合，速度提升百倍。
3. 批次下載後直接處理 MultiIndex，完全向量化運算。
"""
import os
import json
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

    # 如果只有一檔股票，yfinance 返回的不是 MultiIndex，需特殊處理
    if len(tickers_with_suffix) == 1:
        base = tickers_with_suffix[0].split('.')[0]
        df = df[['Close', 'Volume']]
        df.columns = [f"{base}_Close", f"{base}_Volume"]
    else:
        # 處理 MultiIndex，將 ('Close', '2330.TW') 轉為 '2330_Close'
        # 注意：需要把後綴 .TW 或 .TWO 拔掉
        new_columns = []
        for col in df.columns:
            metric = col[0] # 'Close' 或 'Volume'
            ticker = col[1] # '2330.TW'
            if metric in ['Close', 'Volume']:
                base = ticker.split('.')[0]
                new_columns.append(f"{base}_{metric}")
            else:
                new_columns.append(None)
                
        df.columns = new_columns
        df = df.loc[:, df.columns.notnull()] # 只保留 Close 和 Volume

    df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")
    df.index.name = 'Date'
    return df

def get_bulk_data_as_df(base_tickers, period):
    """使用超壓縮格式取得資料，並直接返回整理好的 DataFrame"""
    # 1. 批次 1: 上市 (.TW)
    tw_tickers = [f"{t}.TW" for t in base_tickers]
    print(f"   🚀 [批次 1] 同時下載 {len(tw_tickers)} 檔上市 (.TW) 股票...")
    df_tw = fetch_and_flatten_yf_data(tw_tickers, period)

    # 找出全為 NaN (抓不到資料) 的欄位，推測為上櫃股票
    failed_bases = []
    if not df_tw.empty:
        for base in base_tickers:
            if f"{base}_Close" not in df_tw.columns or df_tw[f"{base}_Close"].dropna().empty:
                failed_bases.append(base)
                # 從 df_tw 中移除無效的欄位
                if f"{base}_Close" in df_tw.columns: df_tw.drop(columns=[f"{base}_Close", f"{base}_Volume"], inplace=True, errors='ignore')

    # 2. 批次 2: 上櫃 (.TWO)
    df_two = pd.DataFrame()
    if failed_bases:
        two_tickers = [f"{t}.TWO" for t in failed_bases]
        print(f"   🚀 [批次 2] 偵測到 {len(failed_bases)} 檔查無資料，切換上櫃 (.TWO) 下載...")
        df_two = fetch_and_flatten_yf_data(two_tickers, period)

    # 3. 合併兩次下載的資料
    if not df_tw.empty and not df_two.empty:
        df_new = pd.concat([df_tw, df_two], axis=1)
    elif not df_tw.empty:
        df_new = df_tw
    else:
        df_new = df_two
        
    return df_new

def main():
    print("===========================================")
    print(f"⚡ 啟動光速批次更新器 (Pandas 向量極速版)")
    print("===========================================")

    # ------------------------------------------------
    # 1. 讀取 Google Sheet (直接轉成 Pandas DataFrame)
    # ------------------------------------------------
    print("☁️ 階段一：讀取 Google Sheet 現有資料庫...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GSPREAD_CREDENTIALS", "{}"))
    
    credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(credentials)
    
    sh = gc.open(SHEET_NAME)
    wks = sh.sheet1
    all_values = wks.get_all_values()
    
    headers = all_values[0]
    df_cloud = pd.DataFrame(all_values[1:], columns=headers)
    df_cloud.set_index('Date', inplace=True)
    
    # 將空白轉為 NaN 以便後續融合
    df_cloud = df_cloud.replace("", np.nan)
    
    # 轉為數值型態
    for col in df_cloud.columns:
        df_cloud[col] = pd.to_numeric(df_cloud[col], errors='coerce')

    target_tickers = get_tickers_from_headers(headers)
    print(f"   ✅ 雲端載入完成，共需更新 {len(target_tickers)} 檔股票。")

    # ------------------------------------------------
    # 2. 批次下載資料
    # ------------------------------------------------
    print(f"\n🕸️ 階段二：光速下載最近 {PERIOD} 資料...")
    df_new = get_bulk_data_as_df(target_tickers, PERIOD)
    
    if df_new.empty:
        print("   ⚠️ 沒有抓到任何新資料，結束程式。")
        return

    # ------------------------------------------------
    # 3. 矩陣融合 (Pandas combine_first 魔法)
    # ------------------------------------------------
    print("\n🧠 階段三：啟動 Pandas 矩陣融合 (補缺漏值)...")
    # 四捨五入處理
    close_cols = [c for c in df_new.columns if c.endswith("_Close")]
    vol_cols = [c for c in df_new.columns if c.endswith("_Volume")]
    df_new[close_cols] = df_new[close_cols].round(2)
    
    # combine_first 邏輯：以 df_new 為主，如果 df_new 是 NaN 或缺少的日期/欄位，就用 df_cloud 補上
    # 這樣完美達成了「更新最新資料」+「保留舊歷史」+「填補空洞」的效果
    df_final = df_new.combine_first(df_cloud)
    
    # 排序日期
    df_final.sort_index(inplace=True)

    # ------------------------------------------------
    # 4. 格式化與寫回 Google Sheet
    # ------------------------------------------------
    print("\n🔄 階段四：格式化並整包覆蓋寫回 Google Sheet...")
    df_final.reset_index(inplace=True)
    
    # 確保原本的 headers 順序不變，並過濾掉可能多出來的爛欄位
    df_final = df_final[[col for col in headers if col in df_final.columns]]
    
    # 格式化輸出
    for col in df_final.columns:
        if col.endswith("_Volume"):
            df_final[col] = df_final[col].apply(lambda x: str(int(x)) if pd.notna(x) else "")
        else:
            df_final[col] = df_final[col].apply(lambda x: str(x) if pd.notna(x) else "")
            
    df_final.fillna("", inplace=True)
    
    output_data = [df_final.columns.tolist()] + df_final.values.tolist()
    
    wks.clear()
    wks.update(range_name="A1", values=output_data) 
    print(f"   🎉 任務完成！Pandas 融合更新結束。")

if __name__ == "__main__":
    main()
