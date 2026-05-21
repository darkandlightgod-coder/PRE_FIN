# -*- coding: utf-8 -*-
"""
V10.1 - 模組 5: 多維度 PCA 預測大腦 (已更新12:58)
功能: 
1. 完美讀取 CSV 所有名單進行 PCA 特徵降維。
2. 運算 5 種時間跨度 (3天, 7天, 1個月, 1年, 5年全資料)。
3. 非線性數學公式破解。
4. 匯出 global_pca_features 雲端報表。
"""
import os, sys, json, traceback, math, time
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
    """全面解析所有提供的 CSV 檔案"""
    files = ["所有上市公司.csv", "所有上櫃公司.csv", "所有興櫃公司.csv", "所有公開發行公司.csv", "所有創櫃公司.csv"]
    tickers = set(TARGETS)
    for f in files:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f, dtype=str)
                if "公司代號" in df.columns:
                    for code in df["公司代號"].dropna():
                        code_str = str(code).strip()
                        if code_str.isdigit() and len(code_str) >= 4:
                            tickers.add(f"{code_str}.TW")
            except: pass
    return list(tickers)

def run_pca_and_nonlinear_math(target, df, window_name, window_size, gc):
    if len(df) < window_size or target not in df.columns:
        return f"[{window_name}] ⚠️ 資料不足。\n"
        
    df_w = df.tail(window_size).copy()
    features = [c for c in df_w.columns if c != 'Date']
    
    returns = df_w[features].pct_change().fillna(0)
    X = returns.values[:-1]
    Y = returns[target].values[1:]
    latest_X = returns.values[-1].reshape(1, -1)
    
    if len(X) < 2: return f"[{window_name}] ⚠️ 樣本過少無法運算。\n"
    
    # 高維度 PCA 運算
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    pca = PCA(n_components=min(10, X_scaled.shape[1], X_scaled.shape[0]))
    X_pca = pca.fit_transform(X_scaled)
    
    if window_name == "alldata" and target == "^TWII" and gc:
        print("   ➤ [alldata 模式] 擷取並匯出高維度 PCA 特徵至 global_pca_features...")
        try:
            wks_features = gc.open("global_pca_features").sheet1
            pca_cols = [f"PC_{i+1}" for i in range(X_pca.shape[1])]
            df_pca_export = pd.DataFrame(X_pca, columns=pca_cols).round(4)
            df_pca_export.insert(0, "Date", df_w['Date'].values[1:])
            wks_features.clear()
            wks_features.update([df_pca_export.columns.values.tolist()] + df_pca_export.astype(str).values.tolist())
            print("   ✅ global_pca_features 特徵矩陣寫入成功！")
        except Exception as e:
            print(f"   ❌ global_pca_features 寫入失敗: {e}")
    
    # 非線性數學解析
    poly = PolynomialFeatures(degree=2, include_bias=False)
    X_poly = poly.fit_transform(X_pca[:, :2])
    
    model = LinearRegression().fit(X_poly, Y)
    score = model.score(X_poly, Y)
    
    latest_X_pca = pca.transform(scaler.transform(latest_X))
    latest_X_poly = poly.transform(latest_X_pca[:, :2])
    pred = model.predict(latest_X_poly)[0]
    
    coefs = model.coef_
    names = poly.get_feature_names_out(['PC1', 'PC2'])
    equation = " + ".join([f"({c:.4f} * {n})" for c, n in zip(coefs, names)])
    
    report = f"🔍 區間: {window_name} (資料量: {len(X)} | 使用矩陣特徵維度: {len(features)})\n"
    report += f"   - 預期漲跌: {pred*100:.2f}%\n"
    report += f"   - 模型 R²: {score:.4f}\n"
    report += f"   - 📐 非線性特徵數學式:\n     Return = {equation}\n"
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
    print("🧠 [模組 5] 啟動 V10.1 多維度預測大腦...")
    try:
        tickers = get_csv_tickers()
        print(f"   ➤ 準備以 400 筆為批次，匯入 {len(tickers)} 檔特徵矩陣，防禦 YF 封鎖...")
        
        df_list = []
        batch_size = 400
        for i in range(0, len(tickers), batch_size):
            chunk = tickers[i:i+batch_size]
            try:
                data = yf.download(chunk, period="5y", group_by="ticker", progress=False, threads=True)
                for t in chunk:
                    if len(chunk) == 1:
                        if 'Close' in data: df_list.append(data['Close'].rename(t))
                    else:
                        if t in data and 'Close' in data[t]:
                            s = data[t]['Close'].dropna()
                            if not s.empty: df_list.append(s.rename(t))
            except Exception as e:
                print(f"   ⚠️ 發生阻擋，啟用容錯備用機制 ({e})")
                break
            time.sleep(1.5)
            
        if not df_list:
            print("❌ 無法獲取任何特徵，中斷預測。")
            return
            
        df_master = pd.concat(df_list, axis=1).ffill().fillna(0).reset_index()
        df_master['Date'] = pd.to_datetime(df_master['Date']).dt.strftime('%Y-%m-%d')
        
        gc = get_gspread_client()
        
        for target in TARGETS:
            print(f"🚀 正在分析標的: {target}")
            full_report = f"📊 V10.1 神諭矩陣預測報告 - {target}\n"
            for w_name, w_size in TIMEFRAMES.items():
                full_report += run_pca_and_nonlinear_math(target, df_master, w_name, w_size, gc)
            
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
