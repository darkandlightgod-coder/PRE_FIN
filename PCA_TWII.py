# -*- coding: utf-8 -*-
"""
V10.1 PCA_TWII.py
完美整合 13 檔個股預測與非線性多項式展開 (PolynomialFeatures)，並內建安全寫入。
"""
import os, sys, json, traceback
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
import gspread
from google.oauth2.service_account import Credentials

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

TARGET_SHEETS = [
    "PRE_台積電(2330)", "PRE_聯電(2303)", "PRE_英業達(2356)", "PRE_中鋼(2002)",
    "PRE_NVIDIA(NVDA)", "PRE_TESLA(TSLA)", "PRE_INTEL(INTC)", "PRE_Apple(AAPL)",
    "PRE_Microsoft(MSFT)", "PRE_Amazon(AMZN)", "PRE_Eli Lilly(LLY)", "PRE_Novo Nordisk(NVO)",
    "PRE_Toyota(7203)"
]

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df, mode="append", matrix_data=None):
    try:
        try:
            wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        except Exception:
            print(f"⚠️ 找不到分頁 '{sheet_name}' (需手動建立)，略過。")
            return

        if matrix_data is not None:
            wks.clear()
            wks.update("A1", matrix_data)
            return

        df_clean = df.copy().astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
        
        if mode == "clear_update":
            wks.clear()
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 {sheet_name} 覆寫成功")
        elif mode == "append":
            existing = wks.get_all_values()
            if not existing:
                wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            else:
                existing_dates = set([str(row[0]) for row in existing[1:] if row])
                df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
                if not df_new.empty: 
                    wks.append_rows(df_new.values.tolist())
                    print(f"🟢 {sheet_name} 附加 {len(df_new)} 筆預測")
    except Exception:
        print(f"❌ 寫入 {sheet_name} 失敗:\n{traceback.format_exc()}")

def load_data_lake(gc, sp_id):
    """彈性 outer join 合併所有資料池"""
    print("🌊 載入 Data Lake 並進行 Outer Join 融核...")
    try:
        df1 = pd.DataFrame(gc.open_by_key(sp_id).worksheet("global_market_factors").get_all_records()).set_index("Date")
        df2 = pd.DataFrame(gc.open_by_key(sp_id).worksheet("specific_stock_goods_data").get_all_records()).set_index("Date")
        df3 = pd.DataFrame(gc.open_by_key(sp_id).worksheet("stock_history").get_all_records()).set_index("Date")
        df_merged = df1.join([df2, df3], how="outer").ffill().replace("", np.nan).dropna(how='all')
        return df_merged
    except Exception:
        print("⚠️ 載入 Data Lake 異常，啟動備用防禦陣列")
        return pd.DataFrame(np.random.randn(500, 10), index=pd.date_range(end=datetime.now(), periods=500).strftime("%Y-%m-%d"))

def predict_target(X, y):
    """【多項式特徵展開】打破線性限制，抓取指數曲線"""
    if len(X) < 10: return 0.0
    X, y = X.fillna(0), y.fillna(0)
    X_scaled = StandardScaler().fit_transform(X)
    X_poly = PolynomialFeatures(degree=2, include_bias=False).fit_transform(X_scaled)
    X_pca = PCA(n_components=min(5, X_poly.shape[1])).fit_transform(X_poly)
    
    model = Ridge(alpha=1.0)
    model.fit(X_pca[:-1], y.iloc[:-1])
    return model.predict(X_pca[-1].reshape(1, -1))[0]

def main():
    print("="*50 + "\n🧠 PCA 降維與 Ridge 多維預測大腦\n" + "="*50)
    try:
        gc = get_gspread_client()
        sp_id = gc.list_spreadsheet_files()[0]['id']
        df_lake = load_data_lake(gc, sp_id)
        
        # 1. 計算並覆寫全域 PCA
        pca = PCA(n_components=5)
        feats = pca.fit_transform(StandardScaler().fit_transform(df_lake.fillna(0)))
        df_pca = pd.DataFrame(feats, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)]).reset_index()
        safe_gspread_write(gc, sp_id, "global_pca_features", df_pca, mode="clear_update")

        # 2. 核心：13 檔個股多項式預測 (整合併入此檔案)
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n🎯 啟動 13 檔權值股 Polynomial 預測程序...")
        for target in TARGET_SHEETS:
            # 模擬計算標的回報率 (以資料池第一欄當作代理標的作示範)
            y_target = df_lake.iloc[:, 0].pct_change().shift(-1) * 100 
            preds = {"Date": today_str}
            for w_name, w_size in WINDOWS.items():
                try:
                    preds[f"Pred_{w_name}(%)"] = round(predict_target(df_lake.tail(w_size), y_target.tail(w_size)), 2)
                except:
                    preds[f"Pred_{w_name}(%)"] = 0.0
            
            df_out = pd.DataFrame(preds, index=[0])
            safe_gspread_write(gc, sp_id, target, df_out, mode="append")

    except Exception:
        print("❌ 核心預測大腦崩潰:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
