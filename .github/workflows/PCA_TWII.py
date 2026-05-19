import os
import sys
import json
import traceback
import pandas as pd
import numpy as np
from datetime import datetime
import importlib

# ==========================================
# 【1. 環境自癒：確保量化與 Google Cloud 依賴庫完整】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 PCA_TWII_Strict_CloudV5.0 運行環境自檢...")
    dependencies = {
        "pandas": "pandas",
        "numpy": "numpy",
        "scikit-learn": "scikit-learn",
        "matplotlib": "matplotlib",
        "tabulate": "tabulate",
        "gspread": "gspread",
        "google-auth": "google-auth",
        "google-api-python-client": "google-api-python-client"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            main_module = module.split('.')[0]
            importlib.import_module(main_module)
        except ImportError:
            print(f"📦 正在自動安裝運作套件: {package}...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 機器學習與 Google 雲端庫部署完畢。")

bootstrap()

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
import matplotlib.pyplot as plt
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==========================================
# 【2. 路徑與環境變數配置】
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

TAIFEX_CSV_PATH = os.path.join(DATA_DIR, "taifex_derivatives_history.csv")
SENTIMENT_CSV_PATH = os.path.join(DATA_DIR, "stock_history.csv")
GLOBAL_CSV_PATH = os.path.join(DATA_DIR, "global_market_factors.csv")
PCA_OUTPUT_PATH = os.path.join(DATA_DIR, "pca_predictions_report.csv")

# 三大雲端特徵源輸入 Google Sheets 對齊
CLOUD_INPUT_MACRO = "global_market_factors"
CLOUD_INPUT_DERIVATIVES = "taifex_derivatives_history"
CLOUD_INPUT_SENTIMENT = "stock_history"

# 雲端輸出 Google Sheets 對齊
CLOUD_OUTPUT_SHEET = "global_pca_features"
CLOUD_REPORT_SHEET = "PCA_PRE_FIN"

# ==========================================
# 【3. 嚴格雲端連接與讀寫校驗模組】
# ==========================================
def connect_google_sheets_strictly():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    
    if not creds_json:
        raise ValueError("❌ [CRITICAL ERROR] 找不到環境變數 GSPREAD_CREDENTIALS！請在 GitHub Secrets 中配置完整的 JSON 憑證！")
    if not folder_id:
        raise ValueError("❌ [CRITICAL ERROR] 找不到環境變數 GOOGLE_DRIVE_FOLDER_ID！請在 GitHub Secrets 中指定目標雲端硬碟資料夾 ID！")
        
    try:
        print("🔑 正在初始化 Google Service Account 安全通道...")
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds_dict = json.loads(creds_json)
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        print("✅ Google Sheets 接口授權成功！")
        return gc, credentials, folder_id
    except Exception as e:
        raise ConnectionError(f"❌ [CRITICAL ERROR] Google API 認證初始化失敗，系統強制中斷！詳細資訊: {str(e)}")

def get_or_create_spreadsheet_in_folder(gc, credentials, folder_id, title):
    try:
        drive_service = build('drive', 'v3', credentials=credentials)
        query = f"name = '{title}' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            spreadsheet_id = files[0]['id']
            print(f"   📂 成功定位雲端資料夾試算表: {title} (ID: {spreadsheet_id})")
            return gc.open_by_key(spreadsheet_id)
        else:
            print(f"   ➕ 雲端目標資料夾中未發現試算表，正在為您全新建立: {title}...")
            file_metadata = {
                'name': title,
                'mimeType': 'application/vnd.google-apps.spreadsheet',
                'parents': [folder_id]
            }
            file = drive_service.files().create(body=file_metadata, fields='id').execute()
            spreadsheet_id = file.get('id')
            print(f"   🎉 雲端試算表建立並定位成功！(ID: {spreadsheet_id})")
            return gc.open_by_key(spreadsheet_id)
    except Exception as e:
        raise IOError(f"❌ [CRITICAL ERROR] 在指定的 Google Drive 資料夾下建立或尋找試算表失敗: {str(e)}")

def verify_cloud_write(worksheet, expected_rows, expected_cols):
    print("🔍 啟動雲端【讀寫一致性校驗機制 (Read-after-Write Verification)】...")
    try:
        values = worksheet.get_all_values()
        actual_rows = len(values)
        actual_cols = len(values[0]) if actual_rows > 0 else 0
        
        print(f"   📊 校驗比對 - 預期規模: {expected_rows}x{expected_cols} | 雲端實際讀回: {actual_rows}x{actual_cols}")
        
        if actual_rows != expected_rows or actual_cols != expected_cols:
            raise ValueError(
                f"❌ [VALIDATION FAILED] 雲端資料讀寫校驗嚴重失真！期望尺寸為 {expected_rows}x{expected_cols}，但雲端實際儲存為 {actual_rows}x{actual_cols}！這條路不夠暢通！"
            )
        print("   ✅ [SUCCESS] 雲端雙向校驗 100% 吻合！確認資料已實體落盤且讀寫完全暢通！")
    except Exception as e:
        raise IOError(f"❌ [CRITICAL ERROR] 執行雲端讀寫一致性校驗時發生致命異常: {str(e)}")

# ==========================================
# 【4. 核心：智慧多源資料庫加載與對齊】
# ==========================================
def load_and_align_datasets():
    print("⏳ [Step 1] 正在啟動嚴格雲端對齊通道...")
    
    # 建立強耦合的 Google 連線。若失敗此處將拋出異常，整個 Actions 會直接亮紅燈報報，絕不降級。
    gc, credentials, folder_id = connect_google_sheets_strictly()
    
    print("☁️ [多因子雲端大合流] 正在讀取三張特徵試算表...")
    try:
        sh_macro = gc.open(CLOUD_INPUT_MACRO)
        df_macro = pd.DataFrame(sh_macro.sheet1.get_all_records())
        
        sh_deriv = gc.open(CLOUD_INPUT_DERIVATIVES)
        df_deriv = pd.DataFrame(sh_deriv.sheet1.get_all_records())
        
        sh_sent = gc.open(CLOUD_INPUT_SENTIMENT)
        df_sent = pd.DataFrame(sh_sent.sheet1.get_all_records())
    except Exception as e:
        raise IOError(f"❌ [CRITICAL ERROR] 讀取雲端三大核心特徵試算表失敗，無法進行合流：{e}")
    
    # 標準化 Date 格式為 YYYY-MM-DD
    for df in [df_macro, df_deriv, df_sent]:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
    
    if "NLP_Engine" in df_sent.columns:
        df_sent = df_sent.drop(columns=["NLP_Engine"])
        
    print(f"   📊 雲端數據規模：總經({len(df_macro)}天), 期權({len(df_deriv)}天), 輿情({len(df_sent)}天)")
    
    # 進行多表 Inner Join 對齊
    df_merged = pd.merge(df_macro, df_deriv, on="Date", how="inner")
    df_final = pd.merge(df_merged, df_sent, on="Date", how="inner")
    
    # 排序日期
    df_final = df_final.sort_values(by="Date").reset_index(drop=True)
    
    if len(df_final) < 5:
        raise ValueError(f"❌ 經時間軸對齊後的有效交集天數過少 ({len(df_final)} 天)，無法進行降維機器學習！")
        
    print(f"   🎯 雲端多源因子對齊完成！共 {len(df_final)} 天。準備同步回雲端試算表...")
    
    # 將對齊後的特徵同步至雲端 global_pca_features
    sync_aligned_data_to_google_drive(gc, credentials, folder_id, df_final)
    
    return df_final

def sync_aligned_data_to_google_drive(gc, credentials, folder_id, df):
    sheet_title = CLOUD_OUTPUT_SHEET
    sh = get_or_create_spreadsheet_in_folder(gc, credentials, folder_id, sheet_title)
    worksheet = sh.sheet1
    worksheet.clear()
    
    df_filled = df.fillna("")
    data_to_sync = [df_filled.columns.values.tolist()] + df_filled.values.tolist()
    
    worksheet.update(values=data_to_sync, range_name="A1")
    print("   🚀 資料寫入雲端中...")
    
    # ⚡ 嚴格雙向驗證
    verify_cloud_write(worksheet, len(data_to_sync), len(df_filled.columns))

# ==========================================
# 【5. 特徵工程與機器學習大腦核心】
# ==========================================
def run_pca_prediction_pipeline(df):
    print("⏳ [Step 2] 正在進行主成分分析 (PCA) 降維...")
    
    exclude_cols = ["Date", "TWII_Close", "TWII_Change", "TWII_Vol_Change"]
    feature_cols = [col for col in df.columns if col not in exclude_cols and df[col].dtype in [np.float64, np.int64]]
    
    X_raw = df[feature_cols].ffill().bfill()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)
    
    pca = PCA(n_components=0.90, svd_solver='full')
    X_pca = pca.fit_transform(X_scaled)
    num_components = X_pca.shape[1]
    print(f"   🔑 成功降維並保留為 {num_components} 個獨立主成分。")
    
    # 預測明日大盤漲跌幅
    df["TWII_Today_Return"] = df["TWII_Close"].pct_change() * 100
    df["TWII_Today_Return"] = df["TWII_Today_Return"].fillna(0.0)
    df['Next_TWII_Change'] = df['TWII_Today_Return'].shift(-1)
    
    X_train = X_pca[:-1]
    y_train = df['Next_TWII_Change'].iloc[:-1].values
    X_predict_tomorrow = X_pca[-1:]
    
    model = Ridge(alpha=15.0)
    model.fit(X_train, y_train)
    pred_return = model.predict(X_predict_tomorrow)[0]
    
    latest_close = df['TWII_Close'].iloc[-1]
    predicted_target_close = latest_close * (1 + (pred_return / 100))
    
    pred_df = pd.DataFrame([{
        "Prediction_Date": (datetime.now() + pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
        "Executed_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "Today_Close": latest_close,
        "Predicted_Return_Pct": pred_return,
        "Predicted_Close": predicted_target_close,
        "Retained_Components": num_components
    }])
    
    # 保存本地快取
    if os.path.exists(PCA_OUTPUT_PATH):
        try:
            old_pred = pd.read_csv(PCA_OUTPUT_PATH)
            pred_df = pd.concat([old_pred, pred_df], ignore_index=True).drop_duplicates(subset=["Prediction_Date"], keep="last")
        except: pass
    pred_df.to_csv(PCA_OUTPUT_PATH, index=False)
    
    # 雲端寫入明日預測報告並啟動驗證
    sync_prediction_report_to_google_drive(pred_df)
    
    return pred_return, latest_close, predicted_target_close, num_components, df

def sync_prediction_report_to_google_drive(report_df):
    gc, credentials, folder_id = connect_google_sheets_strictly()
    sheet_title = CLOUD_REPORT_SHEET
    sh = get_or_create_spreadsheet_in_folder(gc, credentials, folder_id, sheet_title)
    
    worksheet = sh.sheet1
    worksheet.clear()
    
    df_filled = report_df.fillna("")
    report_data = [df_filled.columns.values.tolist()] + df_filled.values.tolist()
    
    worksheet.update(values=report_data, range_name="A1")
    print("   🚀 預測戰情報告寫入雲端中...")
    
    # ⚡ 嚴格雙向驗證
    verify_cloud_write(worksheet, len(report_data), len(df_filled.columns))

# ==========================================
# 【6. 主控程序入口】
# ==========================================
def main():
    print("="*85)
    print("🧠 PCA_TWII V5.0 - 【嚴格雲端強校驗模式】全面啟用！")
    print("="*85)
    try:
        # Step 1: 讀取、對齊，並強行寫入 Google Sheets 對齊數據庫
        df_aligned = load_and_align_datasets()
        
        # Step 2: 執行 PCA 與 Ridge 迴歸，並強行同步預測歷史至 Google Sheet
        pred_return, latest_close, predicted_target, num_comps, df_final = run_pca_prediction_pipeline(df_aligned)
        
        # Step 3: 印出高階量化分析報告
        print("\n" + "="*85)
        print("🎉 【PCA_TWII 雲端寫入、讀回、驗證流程全線完美通關！】")
        print("="*85)
        print(f"📅 歷史資料時間起點：{df_final.iloc[0]['Date']}")
        print(f"📅 歷史資料時間終點：{df_final.iloc[-1]['Date']} (今日最新)")
        print(f"📈 累積大盤對齊天數：{len(df_final)} 天")
        print(f"🔑 保留主成分個數  ：{num_comps} 個獨立主成分")
        print("-" * 85)
        print(f"🔮 【明日台股大盤精準數值預測報告】")
        print(f"   - 🎯 明日預估回報率 (Predicted Return) : {pred_return:+.4f}%")
        print(f"   - 💵 今日大盤收盤價 (Today's Close)     : {latest_close:,.2f}")
        print(f"   - 📈 明日預期收盤價 (Predicted Close)   : {predicted_target:,.2f} 點")
        print(f"   - ⚡ 明日預估漲跌幅 (Predicted Change)  : {predicted_target - latest_close:+.2f} 點")
        print("="*85 + "\n")
        
    except Exception as e:
        print("\n" + "!"*85)
        print("❌ [CRITICAL FATAL ERROR] 雲端管道同步 or 資料校驗失敗！")
        print("!"*85)
        print(f"異常細節: {str(e)}")
        traceback.print_exc()
        print("!"*85 + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
