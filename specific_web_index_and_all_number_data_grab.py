# -*- coding: utf-8 -*-
import os
import json
import pandas as pd
import gspread
import yfinance as yf
from google.oauth2.service_account import Credentials

# ==========================================
# 參數設定區
# ==========================================
SHEET_NAME = "taifex_derivatives_history"
PERIOD = "1mo"  # 每日更新抓近1個月，若要重抓5年可改為 "5y"

def get_tickers_from_headers(headers):
    """掃描表頭，提取所有的基礎股票代號 (不含 .TW)"""
    tickers = set()
    for header in headers:
        if header.endswith("_Close") or header.endswith("_Volume"):
            ticker = header.split('_')[0]
            tickers.add(ticker)
    return sorted(list(tickers))

def extract_series_safely(df, ticker, is_multi):
    """安全地從 Yahoo 批次下載的 DataFrame 中提取單一股票的收盤價與成交量"""
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    
    try:
        # yfinance 批次下載時，如果超過1檔，會返回 MultiIndex DataFrame
        if is_multi:
            close_s = df['Close'][ticker] if 'Close' in df else pd.Series(dtype=float)
            vol_s = df['Volume'][ticker] if 'Volume' in df else pd.Series(dtype=float)
        else:
            close_s = df['Close'] if 'Close' in df else pd.Series(dtype=float)
            vol_s = df['Volume'] if 'Volume' in df else pd.Series(dtype=float)
        return close_s, vol_s
    except Exception:
        # 抓不到該檔股票時，返回空的 Series
        return pd.Series(dtype=float), pd.Series(dtype=float)

def get_bulk_data(base_tickers, period):
    """使用超壓縮格式 (Batch Download) 極速取得資料，並自動切換上市櫃"""
    successful_data = {}
    failed_bases = []

    # 1. 第一次批次攻擊：全部當作上市 (.TW) 抓取
    tw_tickers = [f"{t}.TW" for t in base_tickers]
    print(f"   🚀 [批次 1] 正在同時下載 {len(tw_tickers)} 檔上市 (.TW) 股票...")
    # threads=True 啟用多執行緒，progress=False 關閉進度條以保持終端機乾淨
    df_tw = yf.download(tw_tickers, period=period, threads=True, progress=False)
    
    is_multi_tw = len(tw_tickers) > 1

    # 檢驗哪些成功，哪些失敗
    for base in base_tickers:
        t_tw = f"{base}.TW"
        close_s, vol_s = extract_series_safely(df_tw, t_tw, is_multi_tw)
        
        if close_s.dropna().empty:
            failed_bases.append(base) # 失敗的先存起來
        else:
            successful_data[base] = {'Close': close_s, 'Volume': vol_s}

    # 2. 第二次批次攻擊：把失敗的當作上櫃 (.TWO) 抓取
    if failed_bases:
        two_tickers = [f"{t}.TWO" for t in failed_bases]
        print(f"   🚀 [批次 2] 偵測到 {len(failed_bases)} 檔查無資料，自動切換下載上櫃 (.TWO) 股票...")
        df_two = yf.download(two_tickers, period=period, threads=True, progress=False)
        
        is_multi_two = len(two_tickers) > 1
        
        for base in failed_bases:
            t_two = f"{base}.TWO"
            close_s, vol_s = extract_series_safely(df_two, t_two, is_multi_two)
            
            if not close_s.dropna().empty:
                successful_data[base] = {'Close': close_s, 'Volume': vol_s}
            else:
                print(f"      ⚠️ 放棄：{base} 兩次嘗試皆失敗 (可能是興櫃、下市或異常)")

    return successful_data

def main():
    print("===========================================")
    print(f"⚡ 啟動光速批次更新器 (多執行緒版)")
    print("===========================================")

    # ------------------------------------------------
    # 1. 讀取 Google Sheet
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
    date_idx = headers.index("Date")
    col_idx_map = {name: idx for idx, name in enumerate(headers)}
    
    data_by_date = {}
    for row in all_values[1:]:
        if len(row) > date_idx and row[date_idx]:
            date_str = row[date_idx]
            padded_row = row + [""] * (len(headers) - len(row))
            data_by_date[date_str] = padded_row

    target_tickers = get_tickers_from_headers(headers)
    print(f"   ✅ 共需更新 {len(target_tickers)} 檔股票。")

    # ------------------------------------------------
    # 2. 批次下載資料
    # ------------------------------------------------
    print(f"\n🕸️ 階段二：光速下載最近 {PERIOD} 資料...")
    bulk_data = get_bulk_data(target_tickers, PERIOD)
    
    # ------------------------------------------------
    # 3. 遍歷批次資料，進行智能補完與新增 (rbind)
    # ------------------------------------------------
    print("\n🧠 階段三：將新資料與空值補完寫入記憶體...")
    for base, stock_data in bulk_data.items():
        close_series = stock_data['Close'].dropna()
        vol_series = stock_data['Volume'].dropna()
        
        for date_obj, close_val in close_series.items():
            date_str = date_obj.strftime("%Y-%m-%d")
            
            # 若為新日期則新增一列
            if date_str not in data_by_date:
                new_row = [""] * len(headers)
                new_row[date_idx] = date_str
                data_by_date[date_str] = new_row
            
            # 更新收盤價
            c_col = f"{base}_Close"
            if c_col in col_idx_map:
                c_idx = col_idx_map[c_col]
                if data_by_date[date_str][c_idx] == "":
                    data_by_date[date_str][c_idx] = round(close_val, 2)
            
            # 更新交易量
            v_col = f"{base}_Volume"
            if v_col in col_idx_map and date_obj in vol_series:
                v_idx = col_idx_map[v_col]
                vol_val = vol_series[date_obj]
                if pd.notna(vol_val) and data_by_date[date_str][v_idx] == "":
                    data_by_date[date_str][v_idx] = int(vol_val)

    # ------------------------------------------------
    # 4. 排序與寫回
    # ------------------------------------------------
    print("\n🔄 階段四：排序並整包覆蓋寫回 Google Sheet...")
    sorted_dates = sorted(data_by_date.keys())
    output_data = [headers]
    
    for d in sorted_dates:
        output_data.append(data_by_date[d])
        
    wks.clear()
    wks.update(range_name="A1", values=output_data) 
    print(f"   🎉 任務完成！光速更新結束。")

if __name__ == "__main__":
    main()
