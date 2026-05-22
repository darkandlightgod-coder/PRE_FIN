# -*- coding: utf-8 -*-
"""
V1.0 test.py - Google Sheets 寫入型態除錯探針
目的：模擬所有爬蟲與演算法的真實資料型態，各取 1 筆進行寫入測試，並深度解析報錯原因。
"""
import os, sys, json, traceback
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

def get_gspread_client():
    print("🔑 [初始化] 正在讀取 GSPREAD_CREDENTIALS 憑證...")
    try:
        creds_json = os.environ.get("GSPREAD_CREDENTIALS")
        if not creds_json:
            raise ValueError("找不到環境變數 GSPREAD_CREDENTIALS")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))
    except Exception as e:
        print(f"❌ 憑證讀取失敗: {e}")
        traceback.print_exc()
        sys.exit(1)

def diagnostic_write_test(gc, spreadsheet_id, sheet_name, df, test_name):
    """具備深度型態解析的寫入測試引擎"""
    print("\n" + "="*60)
    print(f"🧪 [測試項目] {test_name} -> 寫入目標分頁: {sheet_name}")
    print("="*60)
    
    try:
        wks = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except Exception as e:
        print(f"❌ 錯誤: 找不到分頁 '{sheet_name}'，請確認 Google Sheet 是否存在此分頁。")
        return

    # 顯示即將寫入的資料與其真實型態
    print("📊 [資料預覽] (僅取前1筆):")
    row_data = df.iloc[0]
    for col, val in row_data.items():
        print(f"   - 欄位 [{col}]: 值 = {val}, 型態 = {type(val)}")

    # ==========================================
    # 💥 第一階段：模擬原始未處理的寫入 (預期可能會在這裡崩潰)
    # ==========================================
    print("\n⚠️ 階段一：嘗試以【原始型態】直接寫入 (模擬目前出錯的狀況)...")
    try:
        raw_values = df.values.tolist()
        wks.append_rows(raw_values)
        print("✅ 階段一成功！代表這組資料型態本來就沒有問題 (例如 stock_history)。")
        return # 如果成功了就不用進行階段二
    except Exception as e:
        print("\n💥 階段一寫入失敗！捕捉到錯誤訊息：")
        print(f"錯誤摘要: {str(e)}")
        print("詳細 Traceback:")
        traceback.print_exc()
        
        print("\n🔍 [深度診斷] 失敗原因通常是因為上述欄位中包含了 numpy.float64, Timestamp 或 NaN。")

    # ==========================================
    # 🛠️ 第二階段：強制字串序列化修復測試
    # ==========================================
    print("\n🛠️ 階段二：啟動【強制字串序列化 (String Casting)】進行修復寫入...")
    try:
        df_clean = df.copy()
        # 將 datetime 轉為標準字串
        if 'Date' in df_clean.columns and pd.api.types.is_datetime64_any_dtype(df_clean['Date']):
            df_clean['Date'] = df_clean['Date'].dt.strftime("%Y-%m-%d")
        
        # 將所有 nan, NaT 替換為空字串，並強制把所有 numpy 數字轉為標準 Python string
        df_clean = df_clean.astype(str).replace({"nan": "", "NaN": "", "NaT": "", "None": "", "<NA>": ""})
        
        clean_values = df_clean.values.tolist()
        wks.append_rows(clean_values)
        print(f"🟢 階段二修復成功！已成功將 1 筆資料寫入 {sheet_name}。")
        print("💡 結論：必須在原始程式碼中加入 `.astype(str).replace(...)` 才能根絕此錯誤。")
    except Exception as e:
        print("\n❌ 階段二修復寫入也失敗，這代表有更深層的結構問題：")
        traceback.print_exc()

def main():
    gc = get_gspread_client()
    try:
        sp_id = gc.list_spreadsheet_files()[0]['id']
        print(f"📄 成功連接試算表 ID: {sp_id}")
    except Exception as e:
        print("❌ 找不到該服務帳號授權的任何試算表。")
        return

    today = datetime.now()
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # ---------------------------------------------------------
    # 測試 1：yfinance 爬蟲資料結構 (包含 numpy float 與缺值 NaN)
    # ---------------------------------------------------------
    print("\n🕸️ 正在獲取測試資料 1 (yfinance)...")
    try:
        yf_data = yf.download(["^TWII", "GC=F"], period="1d", progress=False)['Close'].reset_index()
        yf_data.rename(columns={'index': 'Date', 'Date': 'Date', '^TWII': 'TWII', 'GC=F': 'Gold'}, inplace=True)
        # 故意製造一個缺失值模擬真實情況
        yf_data['Mock_NaN'] = np.nan 
        diagnostic_write_test(gc, sp_id, "global_market_factors", yf_data.tail(1), "yfinance 歷史股價模組")
    except Exception as e:
        print(f"獲取資料 1 失敗: {e}")

    # ---------------------------------------------------------
    # 測試 2：期權籌碼結構 (包含整數、浮點數混合)
    # ---------------------------------------------------------
    df_chips = pd.DataFrame({
        "Date": [pd.Timestamp(today)], # Pandas 特殊時間型態
        "Put_Call_Ratio": [np.float32(1.15)], # Numpy 特殊浮點數
        "Foreign_OI": [np.int64(-5000)] # Numpy 特殊整數
    })
    diagnostic_write_test(gc, sp_id, "taifex_derivatives_history", df_chips, "期貨籌碼整數與浮點數模組")

    # ---------------------------------------------------------
    # 測試 3：唯一成功的 AI 新聞計分結構 (標準 Python 型態)
    # ---------------------------------------------------------
    df_news = pd.DataFrame({
        "Date": [yesterday_str], # 標準 Python 字串
        "X4_Sentiment_Score": [float(0.854)] # 標準 Python 浮點數
    })
    diagnostic_write_test(gc, sp_id, "stock_history", df_news, "AI 新聞語意評分模組 (對照組)")

    # ---------------------------------------------------------
    # 測試 4：PCA 機器學習預測結構 (Numpy 陣列產出物)
    # ---------------------------------------------------------
    # 模擬從 sklearn 模型跑出來的數字
    mock_prediction = np.array([1.23456789]) 
    df_pca = pd.DataFrame({
        "Date": [yesterday_str],
        "Pred_3day(%)": [mock_prediction[0]], # 從 numpy array 提取的值，通常也是 numpy 型態
        "Pred_7day(%)": [np.float64(-0.54)]
    })
    diagnostic_write_test(gc, sp_id, "PRE_台積電(2330)", df_pca, "PCA 多項式機器學習預測模組")

    # ---------------------------------------------------------
    # 測試 5：2D 矩陣戰報結構
    # ---------------------------------------------------------
    print("\n" + "="*60)
    print("🧪 [測試項目] 純二維陣列戰報 -> 寫入目標分頁: PCA_PRE_FIN")
    print("="*60)
    matrix_data = [
        ["📊 測試戰報第一行", today.strftime("%Y-%m-%d %H:%M:%S")],
        ["🏆 測試戰報第二行", "正常 string 型態"]
    ]
    try:
        wks = gc.open_by_key(sp_id).worksheet("PCA_PRE_FIN")
        wks.append_rows(matrix_data)
        print("✅ 二維陣列戰報寫入成功！")
    except Exception as e:
        print("❌ 二維陣列寫入失敗:")
        traceback.print_exc()

    print("\n🎉 所有測試模組執行完畢，請檢視上方的報錯分析。")

if __name__ == "__main__":
    main()
