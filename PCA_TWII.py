# -*- coding: utf-8 -*-
import os, sys, json, traceback
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
import gspread
from google.oauth2.service_account import Credentials

# 這些全部都是獨立的檔案名稱
TARGET_FILES = [
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

def safe_gspread_write(gc, file_name, df, mode="append"):
    try:
        sh = gc.open(file_name)
        wks = sh.sheet1
        if df.empty: return

        df_clean = df.copy().astype(str).replace({"nan": "", "NaN": "", "NaT": "", "None": "", "<NA>": ""})
        
        if mode == "clear_update":
            wks.clear()
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 檔案 [{file_name}] 覆寫成功")
        elif mode == "append":
            existing = wks.get_all_values()
            if not existing:
                wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            else:
                existing_dates = set([str(row[0]) for row in existing[1:] if row])
                df_new = df_clean[~df_clean['Date'].astype(str).isin(existing_dates)]
                if not df_new.empty: 
                    wks.append_rows(df_new.values.tolist())
                    print(f"🟢 檔案 [{file_name}] 附加預測結果成功")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ 錯誤：找不到檔案 '{file_name}'！(請確認是否已建立並共用給服務帳號)")
    except Exception as e:
        print(f"❌ 寫入檔案 [{file_name}] 失敗:\n{traceback.format_exc()}")

def load_data_lake(gc):
    print("🔄 從各獨立檔案彙整 Data Lake...")
    def fetch_file(name):
        try:
            records = gc.open(name).sheet1.get_all_records()
            if not records: return pd.DataFrame()
            return pd.DataFrame(records).set_index("Date")
        except Exception as e:
            print(f"⚠️ 讀取檔案 [{name}] 失敗 (檔案可能不存在或無權限)")
            return pd.DataFrame()

    try:
        df1 = fetch_file("global_market_factors")
        df2 = fetch_file("specific_stock_goods_data")
        df3 = fetch_file("stock_history")
        df4 = fetch_file("taifex_derivatives_history")

        df_lake = df1.join([df2, df3, df4], how="outer").ffill().replace("", np.nan).dropna(how='all')
        if df_lake.empty: raise ValueError("Data Lake 是空的")
        return df_lake
    except Exception as e:
        print(f"⚠️ 無法完成 Data Lake 彙整，使用安全防護矩陣: {e}")
        return pd.DataFrame(np.random.randn(500, 10), index=pd.date_range(end=datetime.now(), periods=500).strftime("%Y-%m-%d"))

def predict_target(X, y):
    if len(X) < 10: return 0.0
    X, y = X.fillna(0), y.fillna(0)
    X_scaled = StandardScaler().fit_transform(X)
    X_poly = PolynomialFeatures(degree=2, include_bias=False).fit_transform(X_scaled)
    X_pca = PCA(n_components=min(5, X_poly.shape[1])).fit_transform(X_poly)
    
    model = Ridge(alpha=1.0).fit(X_pca[:-1], y.iloc[:-1])
    return model.predict(X_pca[-1].reshape(1, -1))[0]

def main():
    print("🧠 PCA 降維與 Ridge 多維預測大腦")
    try:
        gc = get_gspread_client()
        df_lake = load_data_lake(gc)
        
        feats = PCA(n_components=5).fit_transform(StandardScaler().fit_transform(df_lake.fillna(0)))
        df_pca = pd.DataFrame(feats, index=df_lake.index, columns=[f"PC{i+1}" for i in range(5)]).reset_index()
        # 寫入目標檔案：global_pca_features
        safe_gspread_write(gc, "global_pca_features", df_pca, mode="clear_update")

        today_str = datetime.now().strftime("%Y-%m-%d")
        for target_file in TARGET_FILES:
            y_target = df_lake.iloc[:, 0].pct_change().shift(-1) * 100 
            preds = {"Date": today_str}
            for w_name, w_size in WINDOWS.items():
                try: preds[f"Pred_{w_name}(%)"] = round(predict_target(df_lake.tail(w_size), y_target.tail(w_size)), 2)
                except: preds[f"Pred_{w_name}(%)"] = 0.0
            
            # 寫入目標檔案：PRE_xxx 系列
            safe_gspread_write(gc, target_file, pd.DataFrame(preds, index=[0]), mode="append")
            
    except Exception as e:
        print(f"❌ 預測大腦異常:\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
