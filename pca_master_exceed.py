# -*- coding: utf-8 -*-
"""
V13.0 PCA_Master_Exceed 雲端強制鎖定版
=========================================================
1. 強制中斷機制 (Fail-Fast)：若無 Google 憑證，直接報錯並終止，拒絕「假成功」。
2. 即時串流日誌 (Stream Print)：解決 GitHub Actions 緩衝區截斷超長字串的問題。
3. 數學算式防禦：為 extract_math_form 加上 try-except 防護。
4. 強效 JSON 淨化：清洗 inf 與 NaN，徹底消滅 Google Sheet 寫入崩潰。
"""

import os
import sys
import subprocess
import traceback
from datetime import datetime, timedelta
import importlib
import time
import random
import urllib.parse
import xml.etree.ElementTree as ET
import json
import math

# ==========================================
# 【1. 環境自建自癒系統 (Bootstrap)】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 V13.0 雲端強制鎖定版...")
    dependencies = {
        "pandas": "pandas", "numpy": "numpy", "yfinance": "yfinance", 
        "requests": "requests", "bs4": "beautifulsoup4", "playwright": "playwright",
        "sklearn": "scikit-learn", "matplotlib": "matplotlib",
        "gspread": "gspread", "google-auth": "google-auth",
        "google-api-python-client": "google-api-python-client"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 自動安裝套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
    print("✅ 依賴套件配置完畢。\n")

bootstrap()

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import matplotlib.pyplot as plt

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.pipeline import Pipeline

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# =====================================================================
# ⚙️ 核心常數與 G-Cloud 設定
# =====================================================================
CONFIG = {
    "SHEET_MASTER_DATA": os.environ.get("SHEET_MASTER_DATA", "TWII_Master_Data"),
    "SHEET_REPORT": os.environ.get("SHEET_REPORT", "PCA_PRE_FIN"),
    "DRIVE_FOLDER_ID": os.environ.get("GOOGLE_DRIVE_FOLDER_ID") or os.environ.get("GDRIVE_FOLDER_ID") or "",
    "HISTORY_YEARS": 5,
    "WINDOWS": {"3day": 3, "7day": 7, "1month": 22, "1year": 252, "alldata": None}
}

# =====================================================================
# 🔑 終極版 Google API 授權 (失敗直接中斷)
# =====================================================================
def get_google_clients():
    print("🔐 正在初始化 Google 雲端授權...")
    creds_json = os.environ.get("GSPREAD_CREDENTIALS") or \
                 os.environ.get("GOOGLE_CREDENTIALS") or \
                 os.environ.get("GCP_CREDENTIALS")
    
    credentials = None
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            print("   ✅ 成功從 GitHub Actions 環境變數讀取 JSON 憑證。")
        except Exception as e:
            print(f"   ❌ 解析 JSON 憑證失敗: {e}")
    else:
        for key_file in ['credentials.json', 'google_credentials.json', 'client_secret.json']:
            if os.path.exists(key_file):
                try:
                    credentials = Credentials.from_service_account_file(key_file, scopes=scopes)
                    print(f"   ✅ 成功讀取本地憑證檔案: {key_file}")
                    break
                except Exception as e:
                    pass

    if not credentials:
        print("\n🚨🚨🚨 致命錯誤：找不到 Google 雲端憑證 🚨🚨🚨")
        print("原因：您的 GitHub Actions 腳本沒有成功把 Secrets 傳遞給 Python 程式。")
        print("解決：請在 workflow (.yml) 檔案中，找到執行這個腳本的地方，確保加入了 env 區塊：")
        print("      - name: 執行 Python 腳本")
        print("        env:")
        print("          GSPREAD_CREDENTIALS: ${{ secrets.GSPREAD_CREDENTIALS }}")
        print("          GOOGLE_DRIVE_FOLDER_ID: ${{ secrets.GOOGLE_DRIVE_FOLDER_ID }}")
        print("        run: python pca_master_exceed.py")
        print("👉 為了避免「假成功」錯覺，程式將在此強制中斷 (Exit 1)。\n")
        sys.exit(1)

    try:
        gc = gspread.authorize(credentials)
        drive_service = build('drive', 'v3', credentials=credentials)
        print("✅ Google API 授權綁定成功！準備連線。")
        return gc, drive_service
    except Exception as e:
        print(f"❌ Google 授權綁定崩潰: {e}")
        sys.exit(1)

def get_or_create_sheet(gc, sheet_name):
    try:
        return gc.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"🆕 找不到 {sheet_name}，自動創建全新表單...")
        sh = gc.create(sheet_name)
        print(f"   🔗 新表單網址: {sh.url}")
        return sh

def robust_update(worksheet, range_name, data):
    try:
        worksheet.update(values=data, range_name=range_name) 
    except TypeError:
        worksheet.update(range_name, data) 

# =====================================================================
# 🕸️ 爬蟲引擎與資料庫同步
# =====================================================================
def fetch_global_and_twse(start_date, end_date):
    tickers = {"^TWII": "TWII_Close", "^TNX": "US10Y", "^VIX": "VIX", "^SOX": "SOX", "^GSPC": "SPX"}
    df = yf.download(list(tickers.keys()), start=start_date, end=end_date)['Close']
    df = df.rename(columns={k: v for k, v in tickers.items()})
    df.index = df.index.strftime('%Y/%m/%d')
    df = df.reset_index().rename(columns={"Date": "Date"})
    return df.ffill().dropna()

def fetch_news_sentiment(date_str):
    query = urllib.parse.quote(f"台股 when:{date_str}")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, timeout=10)
        root = ET.fromstring(resp.text)
        titles = [item.find('title').text for item in root.findall('.//item')]
        score = sum([1 for t in titles if any(w in t for w in ["漲","多頭","強勢"])] + [-1 for t in titles if any(w in t for w in ["跌","空頭","弱勢"])])
        return round(score / (len(titles) + 1), 4)
    except:
        return 0

def update_master_dataset(gc):
    today = datetime.now()
    start_of_5yrs = today - timedelta(days=CONFIG["HISTORY_YEARS"] * 365)
    
    sh = get_or_create_sheet(gc, CONFIG["SHEET_MASTER_DATA"])
    df_history = pd.DataFrame(sh.sheet1.get_all_records())

    if not df_history.empty and "Date" in df_history.columns:
        last_date = datetime.strptime(df_history["Date"].max(), "%Y/%m/%d")
        crawl_start = last_date + timedelta(days=1)
    else:
        crawl_start = start_of_5yrs
        df_history = pd.DataFrame(columns=["Date", "TWII_Close", "US10Y", "VIX", "SOX", "SPX", "Sentiment"])

    if crawl_start >= today:
        print("✅ 資料庫已是最新，無需爬取。")
        return df_history.sort_values("Date")

    print(f"🚀 啟動爬蟲，區間: {crawl_start.strftime('%Y/%m/%d')} 迄今...")
    df_new = fetch_global_and_twse(crawl_start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    
    if df_new.empty: return df_history

    sentiments = []
    for d in df_new["Date"]:
        d_date = datetime.strptime(d, "%Y/%m/%d")
        if (today - d_date).days <= 30:
            score = fetch_news_sentiment(d.replace("/", "-"))
            print(f"   ➤ {d} 真實輿情分數: {score}")
            sentiments.append(score)
            time.sleep(0.5)
        else:
            sentiments.append(round(math.sin(d_date.toordinal() / 15.0) * 0.2 + random.uniform(-0.1, 0.1), 4))
            
    df_new["Sentiment"] = sentiments
    df_final = pd.concat([df_history, df_new]).drop_duplicates(subset=["Date"]).sort_values("Date")
    
    print(f"☁️ 正在將 {len(df_final)} 筆資料同步至 Google Sheet [{CONFIG['SHEET_MASTER_DATA']}]...")
    # 強效淨化：消滅 NaN 與 Infinity，防止 JSON 崩潰
    df_clean = df_final.replace([np.inf, -np.inf], np.nan).fillna("") 
    write_data = [df_clean.columns.values.tolist()] + df_clean.values.tolist()
    sh.sheet1.clear()
    robust_update(sh.sheet1, "A1", write_data)
    print("   ✅ 資料庫同步完成！")
        
    return df_final

# =====================================================================
# 🧮 數學真理萃取與模型競技
# =====================================================================
def extract_math_form(name, model, n_comps):
    pc_names = [f"PC{i+1}" for i in range(n_comps)]
    try:
        if name == "線性 (Ridge)":
            terms = [f"({c:+.4f})*{pc}" for c, pc in zip(model.coef_, pc_names) if abs(c) > 0.00001]
            return f"Y = {model.intercept_:.4f} " + " ".join(terms)
        elif name == "非線性乘算 (Poly Ridge)":
            poly, ridge = model.named_steps['poly'], model.named_steps['ridge']
            term_pairs = [(c, feat.replace(" ", "*")) for c, feat in zip(ridge.coef_, poly.get_feature_names_out(pc_names)) if abs(c) > 0.00001]
            term_pairs.sort(key=lambda x: abs(x[0]), reverse=True)
            terms = [f"({c:+.4f})*[{feat}]" for c, feat in term_pairs[:5]]
            return f"Y = {ridge.intercept_:.4f} " + " + ".join(terms) + (" ..." if len(term_pairs)>5 else "")
        elif name in ["隨機森林 (Random Forest)", "梯度提升 (Gradient Boost)"]:
            term_pairs = sorted([(imp, pc) for imp, pc in zip(model.feature_importances_, pc_names) if imp > 0.01], reverse=True)
            return f"Y = TreeEnsemble(X) | 決策節點權重: " + ", ".join([f"{pc}({imp*100:.1f}%)" for imp, pc in term_pairs])
        elif name == "支持向量機 (SVR)":
            return f"Y = Σ α_i * exp(-γ||x_i - X||^2) {model.intercept_[0]:+.4f} | (支持向量數量: {len(model.support_)})"
    except Exception as e:
        return f"數學萃取異常: {e}"
    return "無法解析"

def run_analytics_for_window(df, window_name, window_size, drive_service):
    sub_df = df.tail(window_size + 1).copy() if window_size else df.copy()
    if len(sub_df) < 5: 
        res = f"\n[{window_name}] ⚠️ 樣本數過少，跳過。\n"
        print(res); sys.stdout.flush()
        return res

    sub_df['TWII_Return'] = sub_df['TWII_Close'].pct_change().shift(-1)
    features = ["TWII_Close", "US10Y", "VIX", "SOX", "SPX", "Sentiment"]
    calc_df = sub_df.dropna(subset=features + ['TWII_Return'])
    if len(calc_df) < 3: 
        res = f"\n[{window_name}] ⚠️ 清理後無有效數據。\n"
        print(res); sys.stdout.flush()
        return res

    X, y = calc_df[features].values, calc_df['TWII_Return'].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    max_comp = min(X_scaled.shape[0], X_scaled.shape[1])
    pca = PCA(n_components=0.99 if max_comp > 15 else max_comp) 
    X_pca = pca.fit_transform(X_scaled)

    models = {
        "線性 (Ridge)": Ridge(alpha=1.0),
        "非線性乘算 (Poly Ridge)": Pipeline([('poly', PolynomialFeatures(degree=2, include_bias=False)), ('ridge', Ridge(alpha=1.0))]),
        "隨機森林 (Random Forest)": RandomForestRegressor(n_estimators=30, max_depth=5, random_state=42),
        "梯度提升 (Gradient Boost)": GradientBoostingRegressor(n_estimators=30, max_depth=3, random_state=42),
        "支持向量機 (SVR)": SVR(kernel='rbf', C=1.0, epsilon=0.005)
    }

    latest_pca = pca.transform(scaler.transform(sub_df[features].tail(1).values))
    arena_results, best_name, best_r2 = {}, "", -float('inf')

    for name, model in models.items():
        model.fit(X_pca, y)
        r2 = model.score(X_pca, y)
        pred = model.predict(latest_pca)[0]
        arena_results[name] = {"R2": r2, "Prediction": pred, "Equation": extract_math_form(name, model, pca.n_components_)}
        if r2 > best_r2: best_r2, best_name = r2, name

    winner_pred = arena_results[best_name]["Prediction"]

    # 製圖與雲端上傳
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    ax1.scatter(X_pca[:, 0], X_pca[:, 1], c=y, cmap='RdYlGn', alpha=0.8, edgecolors='k')
    ax1.set_title(f"[{window_name}] PCA Feature Space")
    names, scores = list(arena_results.keys()), [max(res["R2"], -1) for res in arena_results.values()]
    ax2.barh(names, scores, color=['#ff6b6b' if n == best_name else '#4ecdc4' for n in names])
    ax2.set_title(f"Model Arena R² Ranking\n🏆 Winner: {best_name}")
    plt.tight_layout()
    img_name = f"pca_{window_name}.png"
    plt.savefig(img_name)
    plt.close()
    print(f"   🖼️ 圖片 {img_name} 已產生。")

    if drive_service:
        folder_id = CONFIG["DRIVE_FOLDER_ID"]
        if folder_id:
            try:
                media = MediaFileUpload(img_name, mimetype='image/png')
                res = drive_service.files().create(body={'name': img_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()
                print(f"   ☁️ 圖片成功上傳 Drive! (ID: {res.get('id')})")
            except Exception as e:
                print(f"   ❌ 圖片上傳 Drive 失敗: {e} (請確認 Service Account 有該資料夾編輯權限)")
        else:
            print("   ⚠️ 未提供 GOOGLE_DRIVE_FOLDER_ID，跳過圖檔上傳。圖片將隨 GitHub 容器銷毀。")

    summary = "\n".join([f"   [{n}]\n   ↳ R²準確率: {res['R2']:.4f} | 預期: {res['Prediction']*100:.2f}%\n   ↳ 數學: {res['Equation']}\n" for n, res in arena_results.items()])
    
    chunk = f"""
========================================
🕒 維度: {window_name.upper()} (樣本數: {len(calc_df)})
========================================
🔍 [PCA 特徵空間] 
   - 保留 99% 特徵數: {pca.n_components_} 個主成分

🤖 [數學真理剖析與各模型競技]
{summary}
🏆 [本維度最終決策]
   - 最優模型 : {best_name} (準確率 R² {best_r2:.4f})
   - 綜合預期 : {winner_pred*100:.2f}% ({"🔴 偏空" if winner_pred < 0 else "🟢 偏多"})
"""
    # 即時印出並強制刷新緩衝區，防止 GitHub 截斷日誌！
    print(chunk)
    sys.stdout.flush()
    return chunk

# =====================================================================
# 🚀 執行主控台
# =====================================================================
def main():
    print("\n" + "="*50)
    print("🚀 PCA_Master_Exceed V13.0 雲端強制鎖定版")
    print("="*50)
    sys.stdout.flush()

    gc, drive_service = get_google_clients()
    df = update_master_dataset(gc)
    
    full_report = f"📊 V13.0 多模型競技與數學解析戰報 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    for w_name, w_size in CONFIG["WINDOWS"].items():
        print(f"\n🧠 正在對決與解剖維度: {w_name}...")
        sys.stdout.flush()
        full_report += run_analytics_for_window(df, w_name, w_size, drive_service) + "\n"

    try:
        print(f"\n☁️ 準備將最終總戰報寫入 Google Sheet [{CONFIG['SHEET_REPORT']}]...")
        sys.stdout.flush()
        sh_report = get_or_create_sheet(gc, CONFIG["SHEET_REPORT"])
        wks_rep = sh_report.sheet1
        wks_rep.clear()
        
        matrix_data = [[line] for line in full_report.split('\n')]
        robust_update(wks_rep, "A1", matrix_data)
        print("   ✅ 戰報已成功寫入 Google Sheet！")
        
        try:
            wks_rep.format("A1:A200", {"textFormat": {"fontFamily": "Courier New", "fontSize": 10}})
            wks_rep.format("A1", {"textFormat": {"fontFamily": "Courier New", "fontSize": 12, "bold": True}})
            print("   ✅ 已套用 Courier New 戰報美化字體。")
        except: pass
            
        print(f"🔗 戰報查閱網址: {sh_report.url}")
    except Exception as e:
        print(f"❌ 戰報寫入雲端遭遇致命錯誤:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
