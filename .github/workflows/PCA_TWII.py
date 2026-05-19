import os
import sys
import json
import traceback
import pandas as pd
import numpy as np
from datetime import datetime
import importlib

# ==========================================
# 【1. 雲端環境自適應安裝與載入】
# ==========================================
def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動 PCA_TWII V4.0 雲端合流自檢...")
    dependencies = {
        "pandas": "pandas",
        "numpy": "numpy",
        "scikit-learn": "scikit-learn",
        "matplotlib": "matplotlib",
        "gspread": "gspread",
        "oauth2client": "oauth2client",
        "googleapiclient": "google-api-python-client",
        "google.auth": "google-auth"
    }

    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            print(f"📦 正在自動安裝量化雲端套件: {package}...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            installed_any = True

    if installed_any:
        importlib.invalidate_caches()
        print("✅ 機器學習分析環境初始化完畢。")

bootstrap()

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
import matplotlib.pyplot as plt
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 【2. 動態路徑與雲端儲存對齊】
# ==========================================
BASE_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(BASE_DIR, exist_ok=True)

# 暫存本機快取路徑
PCA_OUTPUT_LOCAL_PATH = os.path.join(BASE_DIR, "global_pca_features.csv")
DIAGNOSTICS_PLOT_PATH = os.path.join(BASE_DIR, "pca_diagnostics.png")

# 三大雲端特徵源輸入 Google Sheets 對齊
CLOUD_INPUT_MACRO = "global_market_factors"
CLOUD_INPUT_DERIVATIVES = "taifex_derivatives_history"
CLOUD_INPUT_SENTIMENT = "stock_history"

# 雲端輸出 Google Sheets 對齊
CLOUD_OUTPUT_SHEET = "global_pca_features"
CLOUD_REPORT_SHEET = "PCA_PRE_FIN"

FACTOR_TRANSLATION = {
    "SOX_Close": ("Philadelphia Semiconductor Index Close", "費城半導體指數收盤價"),
    "DJI_Close": ("Dow Jones Industrial Average Close", "道瓊工業平均指數收盤價"),
    "IXIC_Close": ("NASDAQ Composite Index Close", "納斯達克綜合指數收盤價"),
    "GSPC_Close": ("S&P 500 Index Close", "標普500指數收盤價"),
    "N225_Close": ("Nikkei 225 Index Close", "日經225指數收盤價"),
    "KS11_Close": ("KOSPI Composite Index Close", "韓國綜合股價指數收盤價"),
    "VIX_Close": ("CBOE Volatility Index Close", "CBOE波動率指數收盤價"),
    "USD_TWD": ("USD to TWD Exchange Rate", "美元兌新台幣匯率"),
    "Gold_Close": ("Gold Futures Close", "黃金期貨收盤價"),
    "CrudeOil_Close": ("WTI Crude Oil Futures Close", "WTI輕原油期貨收盤價"),
    "TSMC_ADR_Close": ("TSMC ADR Close", "台積電 ADR 收盤價"),
    "0050_Close": ("Yuanta Taiwan 50 ETF Close", "元大台灣50 ETF收盤價"),
    "TSMC_Close": ("TSMC Close (2330.TW)", "台積電收盤價"),
    "HonHai_Close": ("Hon Hai Precision Close (2317.TW)", "鴻海收盤價"),
    "MediaTek_Close": ("MediaTek Close (2454.TW)", "聯發科收盤價"),
    "TX_Futures_Close": ("TX Taiwan Index Futures Close", "台指期近月收盤價")
}

def translate_factor(factor_name):
    if factor_name in FACTOR_TRANSLATION:
        return FACTOR_TRANSLATION[factor_name]
    return factor_name.replace("_", " "), factor_name

# ==========================================
# 【3. 雲端認證服務】
# ==========================================
def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope))
        except Exception as e:
            print(f"⚠️ 解析 GSPREAD_CREDENTIALS 失敗: {e}")
            
    local_creds = "credentials.json"
    if os.path.exists(local_creds):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_name(local_creds, scope))
        except: pass
    return None

# ==========================================
# 【4. 數據加載與時間序列預處理】
# ==========================================
def load_and_align_datasets():
    gc = get_gspread_client()
    if not gc:
        raise ConnectionError("❌ 找不到有效的 Google API 認證憑證，無法進行雲端合流！")
        
    print("☁️ [多因子雲端大合流] 正在連線讀取三大核心特徵試算表...")
    
    # 1. 讀取全球總經因子
    sh_macro = gc.open(CLOUD_INPUT_MACRO)
    df_macro = pd.DataFrame(sh_macro.sheet1.get_all_records())
    df_macro["Date"] = pd.to_datetime(df_macro["Date"]).dt.strftime('%Y/%m/%d')
    print(f"   - 全球總經因子庫讀取成功：{len(df_macro)} 天 | {df_macro.shape[1]} 因子")

    # 2. 讀取期權高維籌碼
    sh_deriv = gc.open(CLOUD_INPUT_DERIVATIVES)
    df_deriv = pd.DataFrame(sh_deriv.sheet1.get_all_records())
    df_deriv["Date"] = pd.to_datetime(df_deriv["Date"]).dt.strftime('%Y/%m/%d')
    print(f"   - 期權高維籌碼庫讀取成功：{len(df_deriv)} 天 | {df_deriv.shape[1]} 因子")

    # 3. 讀取輿情分數
    sh_sent = gc.open(CLOUD_INPUT_SENTIMENT)
    df_sent = pd.DataFrame(sh_sent.sheet1.get_all_records())
    df_sent["Date"] = pd.to_datetime(df_sent["Date"]).dt.strftime('%Y/%m/%d')
    if "NLP_Engine" in df_sent.columns:
        df_sent = df_sent.drop(columns=["NLP_Engine"])
    print(f"   - 輿情語意分數庫讀取成功：{len(df_sent)} 天 | {df_sent.shape[1]} 因子")

    # 4. 進行三表 Date 合流
    print("🔄 正在進行時間序列對齊與 Join 合流...")
    df = pd.merge(df_macro, df_deriv, on="Date", how="inner")
    df = pd.merge(df, df_sent, on="Date", how="inner")
    
    df = df.sort_values(by="Date").reset_index(drop=True)
    
    all_nan_cols = df.columns[df.isna().all()].tolist()
    if all_nan_cols:
        df = df.drop(columns=all_nan_cols)
        
    cols_to_fill = df.columns.drop(['Date', 'TWII_Close'])
    df[cols_to_fill] = df[cols_to_fill].ffill().bfill()
    
    remaining_nan = df.columns[df.isna().any()].tolist()
    remaining_nan = [c for c in remaining_nan if c not in ['Date', 'TWII_Close']]
    for col in remaining_nan:
        df[col] = df[col].fillna(df[col].median() if not pd.isna(df[col].median()) else 0.0)
        
    df = df.dropna(subset=['TWII_Close']).reset_index(drop=True)
    
    # 建立 Y 軸預報變數
    df["TWII_Today_Return"] = df["TWII_Close"].pct_change() * 100
    df["TWII_Today_Return"] = df["TWII_Today_Return"].fillna(0.0)
    df["TWII_Tomorrow_Return"] = df["TWII_Today_Return"].shift(-1)
    
    print(f"   ✅ 三表合流完畢！特徵矩陣規模: {df.shape[0]} 天 | {df.shape[1]} 變數。")
    return df

# ==========================================
# 【5. 核心 PCA 降噪與 Ridge 預測引擎】
# ==========================================
def execute_pca_and_prediction_pipeline(df, variance_threshold=0.85):
    print(f"\n🚀 啟動台股降維與脊回歸時間序列預測模型...")
    
    non_feature_cols = ["Date", "TWII_Close", "TWII_Tomorrow_Return", "TWII_Today_Return"]
    feature_cols = [col for col in df.columns if col not in non_feature_cols]
    
    df_train_full = df.dropna(subset=["TWII_Tomorrow_Return"]).reset_index(drop=True)
    df_predict_target = df.iloc[[-1]].reset_index(drop=True)
    
    X_train_full = df_train_full[feature_cols].copy()
    y_train_full = df_train_full["TWII_Tomorrow_Return"].values
    X_predict_today = df_predict_target[feature_cols].copy()
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_full)
    X_predict_scaled = scaler.transform(X_predict_today)
    
    pca = PCA()
    pca.fit(X_train_scaled)
    
    cumulative_variance = np.cumsum(pca.explained_variance_ratio_)
    optimal_k = np.argmax(cumulative_variance >= variance_threshold) + 1
    optimal_k = max(optimal_k, 3) 
    
    print(f"   📈 [解釋變異數盤點]")
    print(f"     * 保留前 {optimal_k} 個主成分 (累積解釋度 {cumulative_variance[optimal_k-1]*100:.2f}%)")
    
    pca_optimal = PCA(n_components=optimal_k)
    X_train_pca = pca_optimal.fit_transform(X_train_scaled)
    X_predict_pca = pca_optimal.transform(X_predict_scaled)
    
    pc_cols = [f"PC_{i+1}" for i in range(optimal_k)]
    df_train_pca = pd.DataFrame(X_train_pca, columns=pc_cols)
    
    correlations = {}
    for col in pc_cols:
        corr_val = np.corrcoef(df_train_pca[col], y_train_full)[0, 1]
        correlations[col] = corr_val
        
    # Ridge 預測與回測
    test_size = min(15, int(len(df_train_full) * 0.15))
    X_tr, X_te = X_train_pca[:-test_size], X_train_pca[-test_size:]
    y_tr, y_te = y_train_full[:-test_size], y_train_full[-test_size:]
    
    model = Ridge(alpha=15.0)
    model.fit(X_tr, y_tr)
    y_te_pred = model.predict(X_te)
    direction_match = (np.sign(y_te_pred) == np.sign(y_te))
    accuracy = np.mean(direction_match) * 100
    
    print(f"   - 模擬測試集方向預測準確率: {accuracy:.2f}%")
    
    # 最終模型訓練
    final_model = Ridge(alpha=15.0)
    final_model.fit(X_train_pca, y_train_full)
    tomorrow_return_pred = final_model.predict(X_predict_pca)[0]
    
    loadings = pd.DataFrame(pca_optimal.components_.T, columns=pc_cols, index=feature_cols)
    df_output_pca = pd.DataFrame(X_train_pca, columns=pc_cols)
    df_output_pca.insert(0, "Date", df_train_full["Date"])
    df_output_pca.insert(1, "TWII_Close", df_train_full["TWII_Close"])
    df_output_pca["TWII_Tomorrow_Return_Actual"] = y_train_full
    df_output_pca["TWII_Tomorrow_Return_Predicted"] = final_model.predict(X_train_pca)
    
    today_row = {
        "Date": df_predict_target.loc[0, "Date"],
        "TWII_Close": df_predict_target.loc[0, "TWII_Close"],
        "TWII_Tomorrow_Return_Actual": np.nan,
        "TWII_Tomorrow_Return_Predicted": tomorrow_return_pred
    }
    for i, col in enumerate(pc_cols):
        today_row[col] = X_predict_pca[0, i]
        
    df_output_pca = pd.concat([df_output_pca, pd.DataFrame([today_row])], ignore_index=True)
    return df_output_pca, pca_optimal, loadings, cumulative_variance, tomorrow_return_pred, accuracy

# ==========================================
# 【6. 可視化與 Google Drive 覆蓋上傳】
# ==========================================
def save_diagnostics_and_plots(pca_model, loadings, cumulative_variance):
    plt.figure(figsize=(14, 6))
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial']  
    plt.rcParams['axes.unicode_minus'] = False
    
    plt.subplot(1, 2, 1)
    plt.plot(range(1, len(cumulative_variance) + 1), cumulative_variance * 100, marker='o', linestyle='--', color='indigo')
    plt.axhline(y=85, color='red', linestyle=':', label='85% 資訊保留線')
    plt.title('主成分累積解釋能力陡峭圖', fontsize=12, fontweight='bold')
    plt.xlabel('主成分個數', fontsize=10)
    plt.ylabel('累積解釋變異數比例 (%)', fontsize=10)
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.legend()
    
    plt.subplot(1, 2, 2)
    pc1_loadings = loadings['PC_1'].sort_values()
    top_loadings = pd.concat([pc1_loadings.head(5), pc1_loadings.tail(5)])
    colors = ['crimson' if val < 0 else 'forestgreen' for val in top_loadings.values]
    top_loadings.plot(kind='barh', color=colors)
    plt.title('第一主成分 (PC_1) 核心權重因子', fontsize=12, fontweight='bold')
    plt.xlabel('因子荷載量 Weight', fontsize=10)
    plt.grid(True, linestyle=':', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(DIAGNOSTICS_PLOT_PATH, dpi=300)
    plt.close()
    print(f"🖼️ 本地診斷分析圖表已生成: {DIAGNOSTICS_PLOT_PATH}")

def upload_plot_to_google_drive(file_path):
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    if not folder_id or not creds_json:
        print("ℹ️ 未偵測到 GOOGLE_DRIVE_FOLDER_ID，跳過雲端圖表備份。")
        return
    try:
        print("\n📤 正在覆蓋上傳 Google Drive 雲端診斷圖檔...")
        creds_dict = json.loads(creds_json)
        scope = ["https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        
        file_name = os.path.basename(file_path)
        query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
        files = results.get('files', [])
        media = MediaFileUpload(file_path, mimetype='image/png', resumable=True)
        
        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"   🔄 [雲端蓋寫成功] 雲端舊圖覆蓋成功 (ID: {file_id})")
        else:
            file_metadata = {'name': file_name, 'parents': [folder_id]}
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print("   📤 [雲端創建成功] 上傳全新診斷圖。")
    except Exception as e:
        print(f"❌ 雲端診斷圖同步失敗: {e}")

# ==========================================
# 【7. 雲端 Google Sheets 自動同步】
# ==========================================
def sync_data_to_google_sheets(df_pca_features, prediction_report_dict):
    gc = get_gspread_client()
    if not gc:
        return
    try:
        print("\n📤 正在同步預測特徵與大盤戰情試算表至 Google Sheets...")
        # 1. 更新主成分寬表
        pca_spreadsheet = gc.open(CLOUD_OUTPUT_SHEET)
        pca_sheet = pca_spreadsheet.sheet1
        pca_sheet.clear()
        df_clean = df_pca_features.fillna("")
        pca_sheet.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
        
        # 2. 覆蓋更新預測戰情表
        pre_spreadsheet = gc.open(CLOUD_REPORT_SHEET)
        pre_sheet = pre_spreadsheet.sheet1
        pre_sheet.clear()
        df_pred = pd.DataFrame([prediction_report_dict])
        pre_sheet.update([df_pred.columns.values.tolist()] + df_pred.values.tolist())
        print("   🎉 [雲端同步完成] PCA 降維分數庫與預報報告更新完畢！")
    except Exception as e:
        print(f"❌ 試算表同步失敗: {e}")

# ==========================================
# 【8. 主執行流】
# ==========================================
def main():
    print("=" * 85)
    print("🧠 PCA_TWII V4.0 - 全面線上化多因子降維預測大腦")
    print("=" * 85)
    
    try:
        df_aligned = load_and_align_datasets()
        
        df_pca_features, pca_model, loadings, cumulative_variance, pred_return, hit_rate = \
            execute_pca_and_prediction_pipeline(df_aligned, variance_threshold=0.85)
        
        save_diagnostics_and_plots(pca_model, loadings, cumulative_variance)
        
        df_pca_features.to_csv(PCA_OUTPUT_LOCAL_PATH, index=False, encoding="utf-8-sig")
        
        latest_close = df_pca_features.dropna(subset=["TWII_Close"]).iloc[-2]["TWII_Close"]
        predicted_target_close = latest_close * (1 + pred_return / 100)
        predicted_change_points = predicted_target_close - latest_close
        
        prediction_report = {
            "Date": df_pca_features.iloc[-1]["Date"],
            "TWII_Today_Close": round(latest_close, 2),
            "TWII_Tomorrow_Predicted_Return_Pct": round(pred_return, 4),
            "TWII_Tomorrow_Predicted_Close": round(predicted_target_close, 2),
            "Expected_Change_Points": round(predicted_change_points, 2),
            "Backtest_Accuracy_Pct": round(hit_rate, 2)
        }
        
        sync_data_to_google_sheets(df_pca_features, prediction_report)
        upload_plot_to_google_drive(DIAGNOSTICS_PLOT_PATH)
        
        print("\n" + "="*85)
        print("🔮 【明日台股大盤精準數值預測日報 (雲端版)】")
        print(f"   - 🎯 明日預估回報率 : {pred_return:+.4f}%")
        print(f"   - 💵 今日大盤收盤價 : {latest_close:,.2f} 點")
        print(f"   - 📈 明日預估收盤價 : {predicted_target_close:,.2f} 點")
        print(f"   - ⚡ 明日預估漲跌點 : {predicted_change_points:+,.2f} 點")
        print(f"   - 🛡️ 模型歷史方向勝率: {hit_rate:.2f}%")
        print("="*85)
        
    except Exception as e:
        print(f"\n❌ 運作失敗: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
