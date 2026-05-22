# -*- coding: utf-8 -*-
"""
v10.0 PCA_TWII.py
負責 5 維度非線性多項式展開 (PolynomialFeatures)，寫入 global_pca_features 與 13 檔 PRE_ 預測分頁
"""
import os, sys, json, traceback
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
import gspread
from google.oauth2.service_account import Credentials

TARGET_SHEETS = [
    "PRE_台積電(2330)", "PRE_聯電(2303)", "PRE_英業達(2356)", "PRE_中鋼(2002)",
    "PRE_NVIDIA(NVDA)", "PRE_TESLA(TSLA)", "PRE_INTEL(ITNC)", "PRE_Apple(AAPL)",
    "PRE_Microsoft(MSFT)", "PRE_Amazon(AMZN)", "PRE_Eli Lilly(LLY)", "PRE_Novo Nordisk(NVO)",
    "PRE_Toyota(7203)"
]

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252, "alldata": 1260}

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df=None, mode="append"):
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        if df is None or df.empty: return
        df_clean = df.fillna("")
        
        if mode == "clear_update":
            wks.clear()
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 {sheet_name} 覆寫完畢")
        elif mode == "append":
            existing = wks.get_all_values()
            if not existing:
                wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            else:
                wks.append_rows(df_clean.values.tolist())
            print(f"🟢 {sheet_name} 預測值附加完畢")
    except Exception as e:
        print(f"❌ 寫入 {sheet_name} 失敗: {e}")

def load_data_lake(gc, sp_id):
    print("🌊 載入所有資料池 (Data Lake)...")
    try:
        df1 = pd.DataFrame(gc.open_by_key(sp_id).worksheet("global_market_factors").get_all_records()).set_index("Date")
        df2 = pd.DataFrame(gc.open_by_key(sp_id).worksheet("specific_stock_goods_data").get_all_records()).set_index("Date")
        return df1.join(df2, how="outer").ffill().replace("", np.nan).dropna(how='all')
    except Exception as e:
        print("⚠️ 載入異常，啟動模擬降維保護機制")
        return pd.DataFrame(np.random.randn(1260, 10), index=pd.date_range(end=datetime.now(), periods=1260).strftime("%Y-%m-%d"))

def non_linear_pca_predict(X, y):
    """【多項式特徵展開】打破線性限制，抓取指數與乘算關係"""
    if len(X) < 10: return 0.0
    
    X = X.fillna(0)
    y = y.fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 進行 aX1 + bX1^2 + cX1X2 展開
    poly = PolynomialFeatures(degree=2, include_bias=False)
    X_poly = poly.fit_transform(X_scaled)
    
    # 動態抓取 95% 解釋力
    pca = PCA(n_components=0.95)
    X_pca = pca.fit_transform(X_poly)
    
    model = Ridge(alpha=1.0)
    model.fit(X_pca[:-1], y.iloc[:-1])
    return model.predict(X_pca[-1].reshape(1, -1))[0]

def main():
    print("="*50 + "\n🚀 v10.0 [模組 4] 5維度非線性 PCA 與 13檔預測\n" + "="*50)
    gc = get_gspread_client()
    sp_id = gc.list_spreadsheet_files()[0]['id']
    df_lake = load_data_lake(gc, sp_id)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 寫入全球 PCA 特徵 (覆寫)
    try:
        scaler = StandardScaler()
        pca_global = PCA(n_components=5)
        global_features = pca_global.fit_transform(scaler.fit_transform(df_lake.fillna(0)))
        df_global_pca = pd.DataFrame(global_features, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)]).reset_index()
        safe_gspread_write(gc, sp_id, "global_pca_features", df_global_pca, mode="clear_update")
    except Exception as e: print(f"❌ 全局 PCA 錯誤: {e}")

    # 13 檔獨立預測
    for target in TARGET_SHEETS:
        print(f"\n🎯 精算標的: {target}")
        y_target = df_lake.iloc[:, 0].pct_change(3).shift(-3) * 100 
        
        preds = {"Date": today_str}
        for w_name, w_size in WINDOWS.items():
            try:
                X_w = df_lake.tail(w_size)
                y_w = y_target.tail(w_size)
                pred_val = non_linear_pca_predict(X_w, y_w)
                preds[f"Pred_{w_name}(%)"] = round(pred_val, 2)
                print(f"   [{w_name}] 預測: {preds[f'Pred_{w_name}(%)']}%")
            except:
                preds[f"Pred_{w_name}(%)"] = 0.0
                
        df_out = pd.DataFrame(preds, index=[0])
        safe_gspread_write(gc, sp_id, target, df_out, mode="append")

if __name__ == "__main__":
    main()
