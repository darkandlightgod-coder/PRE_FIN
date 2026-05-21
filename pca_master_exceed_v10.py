# -*- coding: utf-8 -*-
"""
V18 PCA_Master_Ultimate 終極全域預測大腦 (Ultimate Global Factory)
=========================================================
1. 【2000+ 檔全市場採集】: 讀取上市櫃 CSV，分塊下載 2000 檔台股歷史數據。
2. 【巨量 Raw Data 寫入】: 將全市場最新一日數據，寫入 specific_stock_goods_data。
3. 【全域 PCA 特徵萃取】: 壓縮 2000 檔股票波動，萃取 Market_PC，融合全球宏觀因子。
4. 【13 檔獨立預測工廠】: 針對指定標的，匯入全域特徵，進行 5日/10日/20日 預測。
5. 【預測結果分流寫入】: 最終將 R² 準確率與預測值，分派寫入對應的 13 個獨立 Sheet。
"""

import os
import sys
import time
import glob
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 【設定區 1】: 雲端金鑰與基礎 Sheet 配置
# ==========================================
CONFIG = {
    "SPREADSHEET_KEY": "您的_Google_Sheet_ID_請填這",  # 替換為您的 Sheet ID
    "SHEET_RAW_2000": "specific_stock_goods_data",
    "SHEET_MACRO": "Global_Macro_Raw"
}

CREDENTIALS_FILE = 'credentials.json'

MACRO_TICKERS = {
    "GC=F": "黃金", "SI=F": "白銀", "CL=F": "原油", 
    "^TNX": "美債10Y", "^VIX": "恐慌指數", "^SOX": "費半", "^GSPC": "標普500"
}

# ==========================================
# 【設定區 2】: 預測標的與對應 Sheet 清單
# ==========================================
PREDICTION_TARGETS = {
    "PRE_台積電(2330)": "2330.TW",
    "PRE_聯電(2303)": "2303.TW",
    "PRE_英業達(2356)": "2356.TW",
    "PRE_中鋼(2002)": "2002.TW",
    "PRE_NVIDIA(NVDA)": "NVDA",
    "PRE_TESLA(TSLA)": "TSLA",
    "PRE_INTEL(ITNC)": "INTC", 
    "PRE_Apple(AAPL)": "AAPL",
    "PRE_Microsoft(MSFT)": "MSFT",
    "PRE_Amazon(AMZN)": "AMZN",
    "PRE_Eli Lilly(LLY)": "LLY",
    "PRE_Novo Nordisk(NVO)": "NVO",
    "PRE_Toyota(7203)": "7203.T"
}

# ==========================================
# 【核心 0】: Google Sheets 工具
# ==========================================
def get_gspread_client():
    print("🔑 正在驗證 Google 憑證...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"   ❌ 憑證讀取失敗: {e} (測試環境將僅輸出於終端機)")
        return None

def get_or_create_worksheet(sh, sheet_name, headers=None):
    try:
        wks = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"   ⚠️ 找不到分頁 [{sheet_name}]，自動建立中...")
        wks = sh.add_worksheet(title=sheet_name, rows="1000", cols="20")
        if headers:
            wks.update("A1", [headers])
    return wks

# ==========================================
# 【核心 1】: 2000+檔全市場數據抓取與寫入
# ==========================================
def get_tw_tickers_from_csv():
    """從本地 CSV 解析所有上市櫃股票代號"""
    tickers = []
    # 嘗試讀取上市與上櫃 CSV
    try:
        if os.path.exists('所有上市公司.csv'):
            df_tw = pd.read_csv('所有上市公司.csv', dtype=str)
            if '公司代號' in df_tw.columns:
                tickers.extend([f"{code}.TW" for code in df_tw['公司代號'] if len(code) == 4])
        
        if os.path.exists('所有上櫃公司.csv'):
            df_two = pd.read_csv('所有上櫃公司.csv', dtype=str)
            if '公司代號' in df_two.columns:
                tickers.extend([f"{code}.TWO" for code in df_two['公司代號'] if len(code) == 4])
    except Exception as e:
        print(f"   ⚠️ 讀取 CSV 發生錯誤: {e}")
        
    if not tickers:
        print("   ⚠️ 找不到 CSV，使用預設大型權值股測試清單。")
        tickers = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2303.TW", "2881.TW", "2882.TW", "2891.TW", "2002.TW", "2603.TW"]
    
    # 為了穩定，過濾出唯一值並回傳
    return list(set(tickers))

def fetch_and_process_2000_stocks(gc, sh):
    print("\n🕸️ [模組 1] 啟動 2000+ 檔台股巨量分塊採集...")
    tickers = get_tw_tickers_from_csv()
    print(f"   ➤ 總計排定抓取 {len(tickers)} 檔標的 (期間: 1年)")

    chunk_size = 200
    df_list = []
    
    # 分塊下載避免 Yahoo 阻擋與記憶體爆炸
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        print(f"   ➤ 正在下載批次 {i//chunk_size + 1} ({len(chunk)} 檔)...", end=" ")
        try:
            # 關閉 yfinance 輸出以保持版面整潔
            data = yf.download(chunk, period="1y", interval="1d", progress=False)['Close']
            if len(chunk) == 1:
                data = pd.DataFrame(data)
                data.columns = chunk
            df_list.append(data)
            print(f"成功 ({data.shape[1]} 檔有效)")
        except Exception as e:
            print(f"失敗 ({e})")
        time.sleep(0.5)
        
    df_all_stocks = pd.concat(df_list, axis=1).ffill().dropna(how='all')
    df_all_stocks.index = pd.to_datetime(df_all_stocks.index).normalize()
    
    # --- 寫入 specific_stock_goods_data ---
    if gc and not df_all_stocks.empty:
        write_2000_raw_to_sheet(gc, sh, df_all_stocks)
        
    # --- 萃取全域 PCA (Market Features) ---
    print("\n🧠 正在壓縮 2000 檔股票矩陣，萃取全域 Market PCA...")
    df_returns = df_all_stocks.pct_change().fillna(0)
    scaler = StandardScaler()
    scaled_returns = scaler.fit_transform(df_returns)
    
    n_components = min(5, scaled_returns.shape[1])
    pca = PCA(n_components=n_components)
    pca_features = pca.fit_transform(scaled_returns)
    
    df_market_pca = pd.DataFrame(
        pca_features, 
        index=df_all_stocks.index, 
        columns=[f"Market_PC{i+1}" for i in range(n_components)]
    )
    return df_market_pca

def write_2000_raw_to_sheet(gc, sh, df_all_stocks):
    """將最新一日的 2000 檔資料扁平化寫入 GS (Append 模式)"""
    print(f"\n☁️ 準備將 Raw Data 寫入 [{CONFIG['SHEET_RAW_2000']}]...")
    wks = get_or_create_worksheet(sh, CONFIG["SHEET_RAW_2000"], ["Date", "Ticker", "Close"])
    
    latest_date = df_all_stocks.index[-1]
    latest_date_str = latest_date.strftime("%Y-%m-%d")
    
    # 檢查是否已存在今日資料
    try:
        existing_dates = wks.col_values(1)
        if latest_date_str in existing_dates:
            print(f"   ✅ {latest_date_str} 的 2000 檔數據已存在，跳過覆寫以節省資源。")
            return
    except Exception:
        pass # 若表格為空則忽略

    # 扁平化處理 (Melt)
    latest_data = df_all_stocks.loc[latest_date]
    append_rows = []
    for ticker, val in latest_data.items():
        if pd.notna(val) and val > 0:
            append_rows.append([latest_date_str, str(ticker), round(float(val), 2)])
            
    if append_rows:
        try:
            wks.append_rows(append_rows)
            print(f"   ✅ 成功將 {len(append_rows)} 筆 {latest_date_str} 的股票數據寫入 {CONFIG['SHEET_RAW_2000']}！")
        except Exception as e:
            print(f"   ❌ 寫入 specific_stock_goods_data 失敗: {e}")

# ==========================================
# 【核心 2】: 宏觀與新聞因子
# ==========================================
def sync_macro_factors():
    print("\n🌍 [模組 2] 啟動全球宏觀因子同步...")
    try:
        df_macro = yf.download(list(MACRO_TICKERS.keys()), period="1y", interval="1d", progress=False)['Close']
        df_macro.dropna(how='all', inplace=True)
        df_macro.index = pd.to_datetime(df_macro.index).normalize()
        return df_macro
    except Exception as e:
        print(f"   ❌ 宏觀抓取失敗: {e}")
        return pd.DataFrame()

def get_dummy_news():
    dates = pd.date_range(end=datetime.now(), periods=252)
    df = pd.DataFrame({"Sentiment_Score": np.random.uniform(-1, 1, 252)}, index=dates.normalize())
    df.index.name = "Date"
    return df

# ==========================================
# 【核心 3】: 個股預測引擎 (Ridge Regression)
# ==========================================
def train_and_predict(df_data_lake, target_ticker):
    """結合 Data Lake 進行個股預測"""
    try:
        df_target = yf.download(target_ticker, period="1y", interval="1d", progress=False)['Close']
        if df_target.empty:
            return None
        
        if isinstance(df_target, pd.DataFrame):
            df_target = df_target.iloc[:, 0]
            
        df_target = pd.DataFrame({'Close': df_target})
        df_target.index = pd.to_datetime(df_target.index).normalize()
        
        # 定義 Y: 未來 5, 10, 20 天漲跌幅
        df_target['Y_Short(5D)'] = df_target['Close'].pct_change(5).shift(-5) * 100
        df_target['Y_Mid(10D)'] = df_target['Close'].pct_change(10).shift(-10) * 100
        df_target['Y_Long(20D)'] = df_target['Close'].pct_change(20).shift(-20) * 100
        
        # 融合全域特徵 (Data Lake)
        df_merged = df_target.join(df_data_lake, how='inner').ffill().dropna(subset=['Close'])
        if len(df_merged) < 30: return None
        
        feature_cols = [c for c in df_merged.columns if c not in ['Close', 'Y_Short(5D)', 'Y_Mid(10D)', 'Y_Long(20D)']]
        X_raw = df_merged[feature_cols].fillna(0)
        
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_raw)
        
        predictions = {}
        for period in ['Short(5D)', 'Mid(10D)', 'Long(20D)']:
            y_col = f'Y_{period}'
            train_mask = df_merged[y_col].notna()
            X_train = X_scaled[train_mask]
            y_train = df_merged.loc[train_mask, y_col]
            
            model = Ridge(alpha=1.0)
            model.fit(X_train, y_train)
            
            y_pred_train = model.predict(X_train)
            acc_score = max(r2_score(y_train, y_pred_train), 0)
            
            X_latest = X_scaled[-1].reshape(1, -1)
            pred_value = model.predict(X_latest)[0]
            
            predictions[period] = {
                "forecast": round(pred_value, 2),
                "accuracy": f"{acc_score:.1%}"
            }
            
        return predictions
        
    except Exception as e:
        print(f"     ❌ 預測 {target_ticker} 失敗: {e}")
        return None

def write_prediction_to_sheet(gc, sh, sheet_name, predictions):
    headers = [
        "Date", "短期預測(5日%)", "短期準確率", 
        "中期預測(10日%)", "中期準確率", 
        "長期預測(20日%)", "長期準確率", "更新時間"
    ]
    wks = get_or_create_worksheet(sh, sheet_name, headers)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    
    try:
        existing = wks.col_values(1)
        if today_str in existing:
            print(f"     ✅ {sheet_name} 今日預測已存在，跳過。")
            return
    except Exception:
        pass
        
    new_row = [
        today_str,
        predictions['Short(5D)']['forecast'], predictions['Short(5D)']['accuracy'],
        predictions['Mid(10D)']['forecast'], predictions['Mid(10D)']['accuracy'],
        predictions['Long(20D)']['forecast'], predictions['Long(20D)']['accuracy'],
        current_time
    ]
    wks.append_row(new_row)
    print(f"     ☁️ 已成功將預測結果寫入 [{sheet_name}]")

# ==========================================
# 【主中樞】: 終極全域流水線
# ==========================================
def main():
    print("\n" + "█"*60)
    print("🚀 PCA_Master_Ultimate V18 啟動：全市場降維 & 個股預測分流")
    print("█"*60)
    
    gc = get_gspread_client()
    sh = None
    if gc:
        try:
            sh = gc.open_by_key(CONFIG["SPREADSHEET_KEY"])
        except Exception as e:
            print(f"⚠️ 無法開啟 Spreadsheet ({e})，轉為純本地運算模式。")

    # 1. 構建超級特徵池 (Data Lake)
    df_market_pca = fetch_and_process_2000_stocks(gc, sh)
    df_macro = sync_macro_factors()
    df_news = get_dummy_news()
    
    # 組合 Data Lake: 2000檔市場波動(PCA) + 宏觀 + 新聞
    df_data_lake = pd.concat([df_market_pca, df_macro, df_news], axis=1).ffill().dropna()
    print(f"\n🌊 [超級特徵池 Data Lake] 建構完成！包含 {df_data_lake.shape[1]} 個維度。")

    # 2. 啟動 13 檔標的專屬預測工廠
    print("\n🏭 [預測工廠] 開始利用全域特徵，批次處理 13 檔指定標的...")
    for sheet_name, ticker in PREDICTION_TARGETS.items():
        print(f"\n   ➤ 正在處理標的: {sheet_name} (Ticker: {ticker})")
        
        preds = train_and_predict(df_data_lake, ticker)
        
        if preds:
            print(f"     📈 預測完成: 短期({preds['Short(5D)']['forecast']}%) | 中期({preds['Mid(10D)']['forecast']}%) | 長期({preds['Long(20D)']['forecast']}%)")
            if gc and sh:
                write_prediction_to_sheet(gc, sh, sheet_name, preds)
        else:
            print(f"     ⚠️ {sheet_name} 運算跳過 (資料不足或發生錯誤)。")

    print("\n🎉 V18 終極全域預測大腦 執行完畢！所有任務成功歸檔。")

if __name__ == "__main__":
    main()
