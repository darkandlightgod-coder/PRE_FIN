# -*- coding: utf-8 -*-
"""
V12.1 PCA_TWII.py (增強錯誤追蹤版)
中央大腦架構：讀取 Data Lake -> PCA 降維 -> 派發預測至 13 個獨立檔案
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
# 1. 主資料庫設定 (Data Lake 來源)
# ==========================================
MAIN_DATABASE_ID = "1ZVmajxud7D4uRim8qKPRM4bA_TjnZOxvaZsWja3FKeM"
SOURCE_SHEETS = [
    "global_market_factors", 
    "taifex_derivatives_history", 
    "stock_history_AI_SCORE"
]
PCA_SHEET_NAME = "global_pca_features" 

# ==========================================
# 2. 13檔獨立檔案設定 (預測結果輸出地)
# ==========================================
# ⚠️ 請替換成您真實的 13 個 Google Sheet ID，並記得把 Service Account Email 加入這 13 個檔案的「共用編輯者」中！
TARGET_MAPPING = {
    "PRE_台積電(2330)": {"col": "2330.TW_Close", "file_id": "請填寫_台積電_的GoogleSheet_ID"},
    "PRE_聯電(2303)": {"col": "2303.TW_Close", "file_id": "請填寫_聯電_的GoogleSheet_ID"},
    "PRE_英業達(2356)": {"col": "2356.TW_Close", "file_id": "請填寫_英業達_的GoogleSheet_ID"},
    "PRE_中鋼(2002)": {"col": "2002.TW_Close", "file_id": "請填寫_中鋼_的GoogleSheet_ID"},
    "PRE_NVIDIA(NVDA)": {"col": "NVDA_Close", "file_id": "請填寫_NVIDIA_的GoogleSheet_ID"},
    "PRE_TESLA(TSLA)": {"col": "TSLA_Close", "file_id": "請填寫_TESLA_的GoogleSheet_ID"},
    "PRE_INTEL(INTC)": {"col": "INTC_Close", "file_id": "請填寫_INTEL_的GoogleSheet_ID"},
    "PRE_Apple(AAPL)": {"col": "AAPL_Close", "file_id": "請填寫_Apple_的GoogleSheet_ID"},
    "PRE_Microsoft(MSFT)": {"col": "MSFT_Close", "file_id": "請填寫_Microsoft_的GoogleSheet_ID"},
    "PRE_Amazon(AMZN)": {"col": "AMZN_Close", "file_id": "請填寫_Amazon_的GoogleSheet_ID"},
    "PRE_Eli Lilly(LLY)": {"col": "LLY_Close", "file_id": "請填寫_Lilly_的GoogleSheet_ID"},
    "PRE_Novo Nordisk(NVO)": {"col": "NVO_Close", "file_id": "請填寫_NovoNordisk_的GoogleSheet_ID"},
    "PRE_Toyota(7203)": {"col": "7203.T_Close", "file_id": "請填寫_Toyota_的GoogleSheet_ID"}
}

WINDOWS = {"3day_Return(%)": 3, "7day_Return(%)": 7, "1month_Return(%)": 22, "1year_Return(%)": 252}

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("環境變數 GSPREAD_CREDENTIALS 未設定，請檢查您的金鑰！")
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def safe_gspread_write_to_sheet(gc, spreadsheet_id, sheet_name, df, is_append=False):
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        try:
            wks = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="20")
        
        if is_append:
            existing = wks.get_all_values()
            if existing:
                df_old = pd.DataFrame(existing[1:], columns=existing[0])
                df = pd.concat([df_old, df], ignore_index=True)
                df = df.drop_duplicates(subset=['Date'], keep='last').sort_values('Date')
        
        wks.clear()
        wks.update("A1", [df.columns.tolist()] + df.fillna("").values.tolist())
    except gspread.exceptions.APIError as e:
        print(f"  ❌ Google API 拒絕存取 ({sheet_name})！請檢查是否已將 Service Account Email 加入共用編輯者。錯誤詳情: {e}")
    except Exception as e:
        print(f"  ❌ 寫入主資料庫分頁 {sheet_name} 失敗，未知錯誤: {e}")

def safe_gspread_write_to_independent_file(gc, file_id, df):
    try:
        spreadsheet = gc.open_by_key(file_id)
        wks = spreadsheet.sheet1 
        
        existing = wks.get_all_values()
        if existing:
            df_old = pd.DataFrame(existing[1:], columns=existing[0])
            df = pd.concat([df_old, df], ignore_index=True)
            df = df.drop_duplicates(subset=['Date'], keep='last').sort_values('Date')
            
        wks.clear()
        wks.update("A1", [df.columns.tolist()] + df.fillna("").values.tolist())
        return True
    except gspread.exceptions.APIError as e:
        print(f"  ❌ 獨立檔案 (ID: {file_id}) API 拒絕存取！請確認該檔案有共用給機器人 Email。詳情: {e}")
        return False
    except Exception as e:
        print(f"  ❌ 寫入獨立檔案 {file_id} 失敗: {e}")
        return False

def load_data_lake(gc, spreadsheet_id):
    print("🌊 開始從主資料庫提取並構建 Data Lake...")
    merged_df = None
    
    for sheet in SOURCE_SHEETS:
        try:
            wks = gc.open_by_key(spreadsheet_id).worksheet(sheet)
            data = wks.get_all_values()
            if len(data) < 2: continue
            
            df = pd.DataFrame(data[1:], columns=data[0])
            if 'Date' not in df.columns: continue
            
            df['Date'] = pd.to_datetime(df['Date'])
            for col in df.columns:
                if col != 'Date':
                    df[col] = pd.to_numeric(df[col].replace("", np.nan), errors='coerce')
                    
            if merged_df is None: merged_df = df
            else: merged_df = pd.merge(merged_df, df, on="Date", how="outer")
            print(f"  ✅ 成功載入來源: {sheet}")
            
        except gspread.exceptions.APIError as e:
            print(f"  ❌ 讀取 {sheet} 權限遭拒！請確認主資料庫是否已共用。")
        except gspread.exceptions.WorksheetNotFound:
            print(f"  ⚠️ 找不到分頁 {sheet}，請確認爬蟲是否已成功建立該分頁。")
        except Exception as e:
            print(f"  ❌ 載入來源 {sheet} 發生異常: {e}")
            
    if merged_df is not None:
        merged_df = merged_df.sort_values("Date").ffill().bfill().fillna(0)
    return merged_df

def main():
    print("="*60)
    print("🧠 啟動分散式 PCA 降維與多維非線性預測大腦")
    print("="*60)
    
    try:
        gc = get_gspread_client()
        
        # 1. 取得與合併資料湖
        df_lake = load_data_lake(gc, MAIN_DATABASE_ID)
        if df_lake is None or df_lake.empty:
            print("❌ Data Lake 為空，終止執行。請先確認前三支爬蟲有成功執行並寫入資料！")
            return
            
        # 2. PCA 降維提取
        print("\n🧬 執行 PCA 降維特徵萃取...")
        X_raw = df_lake.drop(columns=['Date'])
        pca = PCA(n_components=5)
        X_pca = pca.fit_transform(StandardScaler().fit_transform(X_raw))
        
        df_pca = pd.DataFrame(X_pca, columns=[f"PC{i+1}" for i in range(5)])
        df_pca.insert(0, 'Date', df_lake['Date'].dt.strftime('%Y-%m-%d'))
        
        safe_gspread_write_to_sheet(gc, MAIN_DATABASE_ID, PCA_SHEET_NAME, df_pca)
        print(f"  ✅ PCA 特徵已更新至主資料庫的 {PCA_SHEET_NAME} 分頁")
        
        # 3. 預測並派發到 13 個獨立檔案
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n🎯 啟動 Polynomial + Ridge 預測，並派發至獨立檔案...")
        
        poly = PolynomialFeatures(degree=2, include_bias=False)
        
        for target_name, config in TARGET_MAPPING.items():
            target_col = config["col"]
            file_id = config["file_id"]
            
            if "請填寫" in file_id:
                print(f"  ⚠️ 尚未填寫 [{target_name}] 的檔案 ID，跳過...")
                continue
                
            if target_col not in df_lake.columns:
                print(f"  ⚠️ 資料庫缺漏欄位 [{target_col}]，跳過 [{target_name}]...")
                continue
                
            pred_record = {"Date": today_str}
            
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
                
            df_pred = pd.DataFrame([pred_record])
            success = safe_gspread_write_to_independent_file(gc, file_id, df_pred)
            if success:
                print(f"  ✅ [{target_name}] 成功派發預測至獨立檔案！")
            
        print("\n🎉 大腦預測與派發任務執行完畢！")

    except Exception as e:
        print(f"\n💥 執行期間發生重大錯誤: {e}")

if __name__ == "__main__":
    main()
