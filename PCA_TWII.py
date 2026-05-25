# -*- coding: utf-8 -*-
"""
V11.0 PCA_TWII.py (Volume to Turnover Value Upgrade)
新增:
1. 完整 13 檔權值股 + 1 檔大盤 (PCA_PRE_TWII) 預測目標清單。
2. 自動特徵工程：動態尋找 Volume 與 Price，並相乘轉換為「成交金額 (Turnover/Value)」。
3. 智慧標的對齊：依照 Sheet 名稱自動尋找 Data Lake 中對應的 Y 值 (目標變數)。
"""
import os, sys, json, traceback, re
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

# ==========================================
# 1. 預測目標 Google Sheet 絕對清單
# ==========================================
TARGET_SHEETS = [
    "PRE_台積電(2330)", "PRE_聯電(2303)", "PRE_英業達(2356)", "PRE_中鋼(2002)",
    "PRE_NVIDIA(NVDA)", "PRE_TESLA(TSLA)", "PRE_INTEL(INTC)", "PRE_Apple(AAPL)", # 註: 幫您修正了 INTEL 的代號為 INTC
    "PRE_Microsoft(MSFT)", "PRE_Amazon(AMZN)", "PRE_Eli Lilly(LLY)", "PRE_Novo Nordisk(NVO)",
    "PRE_Toyota(7203)", 
    "PCA_PRE_TWII" # 大盤指數專用
]

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

# ==========================================
# 2. Google Sheets API 核心
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write(gc, spreadsheet_id, sheet_name, df, mode="append", matrix_data=None):
    try:
        try:
            wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
        except Exception:
            print(f"⚠️ 找不到分頁 '{sheet_name}' (需手動在 Google Sheet 建立此名稱的 Sheet)，略過寫入。")
            return

        if matrix_data is not None:
            wks.clear()
            wks.update("A1", matrix_data)
            return

        df_clean = df.copy().astype(str).replace({"nan": "", "NaN": "", "NaT": ""})
        
        if mode == "clear_update":
            wks.clear()
            wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
            print(f"🟢 {sheet_name} 覆寫成功 (全域 PCA 特徵)")
        elif mode == "append":
            existing = wks.get_all_values()
            if not existing:
                wks.update("A1", [df_clean.columns.tolist()] + df_clean.values.tolist())
                print(f"🟢 {sheet_name} 初始化並寫入 1 筆預測")
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
        print("⚠️ 載入 Data Lake 異常，請確認來源分頁存在。")
        raise

# ==========================================
# 3. 特徵工程：交易量轉成交金額 (Volume * Price)
# ==========================================
def convert_volume_to_value(df):
    """
    動態掃描資料池：找到 Volume 欄位，尋找其對應的 Close/Price 欄位，
    兩者相乘轉換為實質成交金額 (Value)，並捨棄原始 Volume。
    """
    print("\n⚙️ 執行特徵升級：將 [交易量] 轉換為實質 [成交金額] (Volume * Price)...")
    cols = df.columns.tolist()
    
    # 尋找可能代表交易量的欄位 (忽略已經是 Change % 的特徵)
    vol_cols = [c for c in cols if ('vol' in c.lower() or 'volume' in c.lower()) and 'change' not in c.lower()]
    
    for v_col in vol_cols:
        # 提取股票代號或前綴 (例如 "2330_Volume" -> "2330")
        prefix = re.sub(r'_?(volume|vol).*', '', v_col, flags=re.IGNORECASE)
        
        # 尋找對應的價格欄位 (優先找 Close，再來是 Price)
        matched_price_col = None
        for c in cols:
            if prefix in c and ('close' in c.lower() or 'price' in c.lower()):
                matched_price_col = c
                break
                
        if matched_price_col:
            new_col_name = v_col.replace('Volume', 'Value').replace('Vol', 'Value')
            # 確保資料格式為數字後相乘
            try:
                df[new_col_name] = pd.to_numeric(df[v_col], errors='coerce') * pd.to_numeric(df[matched_price_col], errors='coerce')
                print(f"   ✅ 成功轉換: [{v_col}] * [{matched_price_col}] -> [{new_col_name}]")
                # 刪除原始交易量欄位以避免共線性
                df = df.drop(columns=[v_col])
            except Exception as e:
                print(f"   ⚠️ 轉換 {v_col} 時發生數值錯誤: {e}")
                
    return df

# ==========================================
# 4. 機器學習預測大腦
# ==========================================
def extract_target_y(df, sheet_name):
    """根據目標表單名稱，智慧尋找 Data Lake 中對應的收盤價作為 Y 值"""
    # 擷取括號內的代號或特殊名稱 (例如 "2330", "NVDA", "TWII")
    match = re.search(r'\((.*?)\)', sheet_name)
    target_ticker = match.group(1) if match else None
    
    if sheet_name == "PCA_PRE_TWII":
        target_ticker = "TWII"
        
    if target_ticker:
        # 在欄位中尋找包含代號與 Close 的欄位
        for col in df.columns:
            if target_ticker in col and 'close' in col.lower():
                return df[col].pct_change().shift(-1) * 100
                
    # 若找不到精確對應，預設使用第一欄作為代理標的 (Fallback)
    return df.iloc[:, 0].pct_change().shift(-1) * 100

def predict_target(X, y):
    """【多項式特徵展開】打破線性限制，抓取指數曲線"""
    if len(X) < 10: return 0.0
    X, y = X.fillna(0), y.fillna(0)
    
    # 標準化 -> 二次多項式展開 -> PCA 降維抓主成分
    X_scaled = StandardScaler().fit_transform(X)
    X_poly = PolynomialFeatures(degree=2, include_bias=False).fit_transform(X_scaled)
    X_pca = PCA(n_components=min(5, X_poly.shape[1])).fit_transform(X_poly)
    
    # 脊迴歸預測 (防止多項式展開後的過度擬合)
    model = Ridge(alpha=1.0)
    model.fit(X_pca[:-1], y.iloc[:-1]) 
    return model.predict(X_pca[-1].reshape(1, -1))[0]

# ==========================================
# 5. 主程式執行流
# ==========================================
def main():
    print("="*60)
    print("🧠 PCA 降維與 Ridge 多維預測大腦 (成交金額強化版)")
    print("="*60)
    try:
        gc = get_gspread_client()
        sp_id = gc.list_spreadsheet_files()[0]['id']
        
        # 1. 載入並融合資料池
        df_lake = load_data_lake(gc, sp_id)
        
        # 2. 【核心升級】將交易量轉化為成交金額
        df_lake = convert_volume_to_value(df_lake)
        
        # 3. 計算並覆寫全域 PCA (剔除包含字串的欄位以利 PCA 計算)
        df_numeric = df_lake.apply(pd.to_numeric, errors='coerce').fillna(0)
        pca = PCA(n_components=5)
        feats = pca.fit_transform(StandardScaler().fit_transform(df_numeric))
        df_pca = pd.DataFrame(feats, index=df_numeric.index, columns=[f"PC{i+1}" for i in range(5)]).reset_index()
        safe_gspread_write(gc, sp_id, "global_pca_features", df_pca, mode="clear_update")

        # 4. 對 14 個目標分頁進行獨立運算與寫入
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n🎯 啟動 {len(TARGET_SHEETS)} 檔權值標的 Polynomial 預測程序...")
        
        for target in TARGET_SHEETS:
            # 智慧提取該標的專屬的 Y 值 (未來報酬率)
            y_target = extract_target_y(df_numeric, target)
            
            preds = {"Date": today_str}
            for w_name, w_size in WINDOWS.items():
                try:
                    # 擷取特定時間窗格的資料進行擬合
                    window_X = df_numeric.tail(w_size)
                    window_y = y_target.tail(w_size)
                    preds[f"Pred_{w_name}(%)"] = round(predict_target(window_X, window_y), 2)
                except Exception as e:
                    preds[f"Pred_{w_name}(%)"] = 0.0
            
            df_out = pd.DataFrame(preds, index=[0])
            # 將預測結果追加至該專屬 Sheet 中
            safe_gspread_write(gc, sp_id, target, df_out, mode="append")

        print("\n🎉 預測運算全部完成！")

    except Exception:
        print("❌ 核心預測大腦崩潰:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
