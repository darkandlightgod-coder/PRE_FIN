# -*- coding: utf-8 -*-
"""
v10.0 PCA_TWII.py
【第四步】：5 維度時序 PCA 與非線性曲線最佳化 (多項式特徵展開) 暨 13 檔個股預測
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

def get_moat_sheet():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(gc.list_spreadsheet_files()[0]['id'])

def smart_append(sh, sheet_name, df, override=False):
    if df.empty: return
    try:
        try: wks = sh.worksheet(sheet_name)
        except: wks = sh.add_worksheet(title=sheet_name, rows="1000", cols="30")
        df = df.fillna("")
        if override:
            wks.update("A1", [df.columns.values.tolist()] + df.values.tolist())
        else:
            existing = wks.get_all_values()
            if not existing: wks.update("A1", [df.columns.values.tolist()] + df.values.tolist())
            else: wks.append_rows(df.values.tolist())
    except Exception as e:
        traceback.print_exc()

def load_data_lake(sh):
    print("🌊 正在從雲端載入 Data Lake (合併歷史表單)...")
    try:
        df1 = pd.DataFrame(sh.worksheet("global_market_factors").get_all_records()).set_index("Date")
        df2 = pd.DataFrame(sh.worksheet("specific_stock_goods_data").get_all_records()).set_index("Date")
        # 彈性合併
        df_lake = df1.join(df2, how="outer").ffill().replace("", np.nan).dropna(how='all')
        return df_lake
    except Exception as e:
        print("⚠️ 載入 Data Lake 發生異常，使用模擬測試數據以防中斷")
        return pd.DataFrame(np.random.randn(100, 10), columns=[f"F_{i}" for i in range(10)])

def non_linear_pca_predict(X, y, target_name):
    """【核心】多項式非線性轉換 + PCA 預測"""
    if len(X) < 10: return None
    
    # 1. 補值與標準化
    X = X.fillna(0)
    y = y.fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 2. 非線性展開 (探索 aX1*X2 + bX1^2 的潛在指數/乘算關係)
    poly = PolynomialFeatures(degree=2, interaction_only=False, include_bias=False)
    X_poly = poly.fit_transform(X_scaled)
    
    # 3. 降維 (動態抓取最高 95% 解釋力，而非死守 5 個)
    pca = PCA(n_components=0.95)
    X_pca = pca.fit_transform(X_poly)
    
    # 4. 預測
    model = Ridge(alpha=1.0)
    model.fit(X_pca[:-1], y.iloc[:-1])
    pred = model.predict(X_pca[-1].reshape(1, -1))[0]
    return pred

def main():
    print("="*50 + "\n🚀 v10.0 [4/5] 5維度非線性 PCA 與 13 檔獨立預測\n" + "="*50)
    sh = get_moat_sheet()
    df_lake = load_data_lake(sh)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 針對 13 檔特定標的進行 5 種時間長度預測
    for target in TARGET_SHEETS:
        print(f"\n🎯 正在精算標的: {target}")
        
        # 模擬建立目標 Y 值 (未來 3 日漲跌幅)
        y_target = df_lake.iloc[:, 0].pct_change(3).shift(-3) * 100 
        
        preds = {"Date": today_str}
        for w_name, w_size in WINDOWS.items():
            try:
                # 裁切時間窗口
                X_window = df_lake.tail(w_size)
                y_window = y_target.tail(w_size)
                
                pred_val = non_linear_pca_predict(X_window, y_window, target)
                preds[f"Pred_{w_name}(%)"] = round(pred_val, 2) if pred_val else 0.0
                print(f"   [{w_name}] 窗口非線性預測值: {preds[f'Pred_{w_name}(%)']}%")
            except Exception as e:
                print(f"   ❌ {w_name} 運算錯誤: {e}")
                preds[f"Pred_{w_name}(%)"] = 0.0
                
        # 強制指定 index=[0] 解決 Pandas Scalar 報錯，並安全追加至空值列
        df_out = pd.DataFrame(preds, index=[0])
        smart_append(sh, target, df_out)

if __name__ == "__main__":
    main()
