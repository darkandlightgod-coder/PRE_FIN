# -*- coding: utf-8 -*-
"""
V14.0 PCA_TWII.py (全獨立檔案微服務 - 智慧尋名版)
中央大腦：無需填寫 ID，直接依賴 Service Account 權限，透過「檔案名稱」自動尋找 Google Sheet。
讀取 3 個來源檔 -> 寫入 1 個 PCA 檔 -> 派發至 13 個預測檔。
"""
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 獨立輸入來源設定 (3個 Data Lake 檔案名稱)
# ==========================================
SOURCE_FILE_NAMES = [
    "stock_history_AI_SCORE",
    "global_market_factors",
    "taifex_derivatives_history"
]

# ==========================================
# 2. 獨立 PCA 特徵輸出檔案名稱
# ==========================================
PCA_OUTPUT_FILE_NAME = "global_pca_features"

# ==========================================
# 3. 獨立 13檔預測輸出檔案設定 (檔名對應預測目標欄位)
# ==========================================
TARGET_MAPPING = {
    "PRE_台積電(2330)": "2330.TW_Close",
    "PRE_聯電(2303)": "2303.TW_Close",
    "PRE_英業達(2356)": "2356.TW_Close",
    "PRE_中鋼(2002)": "2002.TW_Close",
    "PRE_NVIDIA(NVDA)": "NVDA_Close",
    "PRE_TESLA(TSLA)": "TSLA_Close",
    "PRE_INTEL(INTC)": "INTC_Close",
    "PRE_Apple(AAPL)": "AAPL_Close",
    "PRE_Microsoft(MSFT)": "MSFT_Close",
    "PRE_Amazon(AMZN)": "AMZN_Close",
    "PRE_Eli Lilly(LLY)": "LLY_Close",
    "PRE_Novo Nordisk(NVO)": "NVO_Close",
    "PRE_Toyota(7203)": "7203.T_Close"
}

WINDOWS = {"3day_Return(%)": 3, "7day_Return(%)": 7, "1month_Return(%)": 22, "1year_Return(%)": 252}

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("環境變數 GSPREAD_CREDENTIALS 未設定，請檢查您的金鑰！")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_write_to_independent_file_by_name(gc, file_name, df, is_append=False):
    """透過檔案名稱尋找並寫入資料 (永遠寫入 Sheet1)"""
    try:
        # 直接使用檔名開啟，若有多個同名檔案會開啟第一個
        spreadsheet = gc.open(file_name)
        wks = spreadsheet.sheet1
        
        if is_append:
            existing = wks.get_all_values()
            if existing:
                df_old = pd.DataFrame(existing[1:], columns=existing[0])
                df = pd.concat([df_old, df], ignore_index=True)
                if 'Date' in df.columns:
                    df = df.drop_duplicates(subset=['Date'], keep='last').sort_values('Date')
            
        wks.clear()
        wks.update("A1", [df.columns.tolist()] + df.fillna("").values.tolist())
        return True
        
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"  ❌ 找不到檔案名稱為 [{file_name}] 的 Google Sheet，請確認您已建立該檔案且共用權限正確！")
        return False
    except gspread.exceptions.APIError as e:
        print(f"  ❌ API 拒絕存取 [{file_name}]！權限不足或超出請求配額。")
        return False
    except Exception as e:
        print(f"  ❌ 寫入 [{file_name}] 失敗: {e}")
        return False

def load_distributed_data_lake_by_name(gc, source_names):
    """透過檔案名稱從多個獨立的 Google Sheet 提取資料並合併成 Data Lake"""
    print("🌊 開始從雲端硬碟搜尋並提取 Data Lake...")
    merged_df = None
    
    for name in source_names:
        try:
            spreadsheet = gc.open(name)
            wks = spreadsheet.sheet1
            data = wks.get_all_values()
            
            if len(data) < 2: 
                print(f"  ⚠️ 來源 [{name}] 內沒有足夠的資料列，跳過。")
                continue
            
            df = pd.DataFrame(data[1:], columns=data[0])
            if 'Date' not in df.columns: 
                print(f"  ⚠️ 來源 [{name}] 找不到 'Date' 欄位，跳過。")
                continue
            
            # --- 日期髒資料清洗防禦機制 ---
            df['Date'] = df['Date'].astype(str).str.strip()
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce') 
            df = df.dropna(subset=['Date']) 
            
            if df.empty:
                print(f"  ⚠️ 來源 [{name}] 內沒有合法的日期資料，跳過。")
                continue

            for col in df.columns:
                if col != 'Date':
                    df[col] = pd.to_numeric(df[col].replace("", np.nan), errors='coerce')
                    
            if merged_df is None: 
                merged_df = df
            else: 
                merged_df = pd.merge(merged_df, df, on="Date", how="outer")
                
            print(f"  ✅ 成功載入來源: [{name}] (有效筆數: {len(df)})")
            
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"  ❌ 找不到檔案 [{name}]，請確認檔名完全一致且已共用。")
        except Exception as e:
            print(f"  ❌ 載入來源 [{name}] 發生異常: {e}")
            
    if merged_df is not None and not merged_df.empty:
        merged_df = merged_df.sort_values("Date").ffill().bfill().fillna(0)
        
    return merged_df

def main():
    print("="*60)
    print("🧠 啟動全獨立檔案微服務架構 (智慧尋檔版)")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        
        # 1. 取得與合併資料湖
        df_lake = load_distributed_data_lake_by_name(gc, SOURCE_FILE_NAMES)
        
        if df_lake is None or df_lake.empty:
            print("❌ Data Lake 組合失敗或為空，終止執行。請確認來源檔案皆存在且有資料。")
            return
            
        # 2. PCA 降維提取 (寫入獨立 PCA 檔案)
        print("\n🧬 執行 PCA 降維特徵萃取...")
        X_raw = df_lake.drop(columns=['Date'])
        # 確保有足夠的特徵欄位做PCA，避免欄位不足5個報錯
        n_components = min(5, X_raw.shape[1]) 
        pca = PCA(n_components=n_components)
        X_pca = pca.fit_transform(StandardScaler().fit_transform(X_raw))
        
        df_pca = pd.DataFrame(X_pca, columns=[f"PC{i+1}" for i in range(n_components)])
        df_pca.insert(0, 'Date', df_lake['Date'].dt.strftime('%Y-%m-%d'))
        
        # 覆寫模式寫入 PCA 獨立檔案
        success_pca = safe_write_to_independent_file_by_name(gc, PCA_OUTPUT_FILE_NAME, df_pca, is_append=False)
        if success_pca:
            print(f"  ✅ PCA 特徵已成功更新至 [{PCA_OUTPUT_FILE_NAME}]")
            
        # 3. 預測並派發到 13 個獨立檔案
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n🎯 啟動 Polynomial + Ridge 預測，自動尋找 13 個目標檔案派發...")
        
        poly = PolynomialFeatures(degree=2, include_bias=False)
        
        for file_name, target_col in TARGET_MAPPING.items():
            if target_col not in df_lake.columns:
                print(f"  ⚠️ Data Lake 中缺少目標股價欄位 [{target_col}]，跳過派發至 [{file_name}]...")
                continue
                
            pred_record = {"Date": today_str}
            
            # 計算四個週期的回報率並訓練模型
            for w_name, w_days in WINDOWS.items():
                y = df_lake[target_col].pct_change(w_days).shift(-w_days) * 100
                valid_idx = y.notna()
                X_train, y_train = X_pca[valid_idx], y[valid_idx]
                
                if len(X_train) == 0:
                    pred_record[w_name] = 0.0
                    continue
                    
                X_train_poly = poly.fit_transform(X_train)
                model = Ridge(alpha=1.0)
                model.fit(X_train_poly, y_train)
                
                X_latest_poly = poly.transform([X_pca[-1]])
                pred_record[w_name] = round(model.predict(X_latest_poly)[0], 4)
                
            # 附加模式 (Append) 寫入獨立檔案
            df_pred = pd.DataFrame([pred_record])
            success = safe_write_to_independent_file_by_name(gc, file_name, df_pred, is_append=True)
            if success:
                print(f"  ✅ 成功派發預測至 [{file_name}]！")
            
        print("\n🎉 全部分散式派發任務執行完畢！")

    except Exception as e:
        print(f"\n💥 執行期間發生重大錯誤: {e}")

if __name__ == "__main__":
    main()
