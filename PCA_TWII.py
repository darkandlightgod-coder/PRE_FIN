# -*- coding: utf-8 -*-
"""
V10.0 - 模組 5: 多維度 PCA 預測大腦 (5種時間維度 + 非線性數學解析)
功能: 
1. 解析 CSV 檔案作為 YFinance 大量特徵白名單。
2. 運算 5 種時間跨度 (3天, 7天, 1個月, 1年, 5年全資料)。
3. PolynomialFeatures 非線性數學公式破解 (a*X1 + b*X2 + c*X1X2...)。
4. 針對 14 個標的寫入專屬 Google Sheet。
"""
import os, sys, json, traceback, math
import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import LinearRegression
import gspread
from google.oauth2.service_account import Credentials
import warnings
warnings.filterwarnings('ignore')

TARGETS = ["^TWII", "2330.TW", "2303.TW", "2356.TW", "2002.TW", "NVDA", "TSLA", "INTC", "AAPL", "MSFT", "AMZN", "LLY", "NVO", "7203.T"]
TIMEFRAMES = {"3day": 3, "7day": 7, "1month": 21, "1year": 252, "alldata": 1250}

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json: return None
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def get_csv_tickers():
    """解析目錄下所有 CSV 獲取真實台股清單"""
    files = ["所有上市公司.csv", "所有上櫃公司.csv", "所有興櫃公司.csv", "所有公開發行公司.csv", "所有創櫃公司.csv"]
    tickers = set(TARGETS)
    for f in files:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f, dtype=str)
                if "公司代號" in df.columns:
                    for code in df["公司代號"].dropna():
                        if code.isdigit() and len(code) >= 4: tickers.add(f"{code}.TW")
            except: pass
    return list(tickers)[:150] # 為避免 YFinance 記憶體爆掉，取樣 150 檔作為特徵矩陣

def run_pca_and_nonlinear_math(target, df, window_name, window_size):
    if len(df) < window_size or target not in df.columns:
        return f"[{window_name}] ⚠️ 資料不足。\n"
        
    df_w = df.tail(window_size).copy()
    features = [c for c in df_w.columns if c != 'Date']
    
    returns = df_w[features].pct_change().fillna(0)
    X = returns.values[:-1]
    Y = returns[target].values[1:]
    latest_X = returns.values[-1].reshape(1, -1)
    
    if len(X) < 2: return f"[{window_name}] ⚠️ 樣本過少無法運算。\n"
    
    # 1. 傳統 PCA
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    pca = PCA(n_components=min(5, X_scaled.shape[1], X_scaled.shape[0]))
    X_pca = pca.fit_transform(X_scaled)
    
    # 2. 非線性數學解析 (Polynomial Interaction Degree=2)
    # 解構公式: Y = a*PC1 + b*PC2 + c*PC1^2 + d*PC1*PC2 + e*PC2^2
    poly = PolynomialFeatures(degree=2, include_bias=False)
    X_poly = poly.fit_transform(X_pca[:, :2]) # 取前兩個 PC 分析非線性
    
    model = LinearRegression().fit(X_poly, Y)
    score = model.score(X_poly, Y)
    
    latest_X_pca = pca.transform(scaler.transform(latest_X))
    latest_X_poly = poly.transform(latest_X_pca[:, :2])
    pred = model.predict(latest_X_poly)[0]
    
    coefs = model.coef_
    names = poly.get_feature_names_out(['PC1', 'PC2'])
    equation = " + ".join([f"({c:.4f} * {n})" for c, n in zip(coefs, names)])
    
    report = f"🔍 區間: {window_name} (資料量: {len(X)})\n"
    report += f"   - 預期漲跌: {pred*100:.2f}%\n"
    report += f"   - 模型 R²: {score:.4f}\n"
    report += f"   - 📐 非線性特徵解構數學式:\n     Return = {equation}\n"
    report += "-"*40 + "\n"
    return report

def get_sheet_name(target):
    mapping = {
        "^TWII": "5in1", "2330.TW": "PRE_台積電(2330)", "2303.TW": "PRE_聯電(2303)",
        "2356.TW": "PRE_英業達(2356)", "2002.TW": "PRE_中鋼(2002)", "NVDA": "PRE_NVIDIA(NVDA)",
        "TSLA": "PRE_TESLA(TSLA)", "INTC": "PRE_INTEL(INTC)", "AAPL": "PRE_Apple(AAPL)",
        "MSFT": "PRE_Microsoft(MSFT)", "AMZN": "PRE_Amazon(AMZN)", "LLY": "PRE_Eli Lilly(LLY)",
        "NVO": "PRE_Novo Nordisk(NVO)", "7203.T": "PRE_Toyota(7203)"
    }
    return mapping.get(target, f"PRE_{target}")

def main():
    print("🧠 [模組 5] 啟動 V10.0 多維度預測大腦...")
    try:
        tickers = get_csv_tickers()
        print(f"   ➤ 從 CSV 載入 {len(tickers)} 檔特徵矩陣，開始歷史爬取...")
        df_yf = yf.download(tickers, period="5y", group_by="ticker", progress=False)
        
        df_list = []
        for t in tickers:
            if t in df_yf and 'Close' in df_yf[t]:
                s = df_yf[t]['Close'].dropna()
                if not s.empty: df_list.append(s.rename(t))
                
        df_master = pd.concat(df_list, axis=1).ffill().fillna(0).reset_index()
        df_master['Date'] = pd.to_datetime(df_master['Date']).dt.strftime('%Y-%m-%d')
        
        gc = get_gspread_client()
        
        for target in TARGETS:
            print(f"🚀 正在分析標的: {target}")
            full_report = f"📊 V10.0 神諭矩陣預測報告 - {target}\n"
            for w_name, w_size in TIMEFRAMES.items():
                full_report += run_pca_and_nonlinear_math(target, df_master, w_name, w_size)
            
            if gc:
                sheet_title = get_sheet_name(target)
                try:
                    wks = gc.open(sheet_title).sheet1
                    wks.clear()
                    matrix = [[line] for line in full_report.split('\n')]
                    wks.update("A1", matrix)
                    print(f"   ✅ 戰報寫入 {sheet_title}！")
                except gspread.exceptions.SpreadsheetNotFound:
                    print(f"   ❌ 找不到 '{sheet_title}'，請先手動建立！")
                    
        print("✅ [模組 5] 預測完成！\n")
    except Exception as e:
        print(f"❌ [模組 5] 發生嚴重錯誤:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
