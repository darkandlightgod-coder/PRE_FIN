# -*- coding: utf-8 -*-
"""
負責整合報告寫入 [PCA_PRE_FIN] (覆寫矩陣) 與 [5in1] (系統日誌)
"""
import os, sys, json
from datetime import datetime
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

def safe_gspread_write(gc, spreadsheet_key, sheet_name, df=None, mode="append", matrix_data=None):
    try:
        sh = gc.open_by_key(spreadsheet_key)
        wks = sh.worksheet(sheet_name)
    except Exception as e:
        print(f"❌ 錯誤: 找不到分頁 '{sheet_name}' (請先手動建立)。")
        return

    try:
        if matrix_data is not None:
            wks.clear()
            wks.update("A1", matrix_data)
            print(f"🟢 成功覆寫戰報至 {sheet_name}")
            return
            
        if df is None or df.empty: return
        df_clean = df.fillna("")
        if mode == "append":
            wks.append_rows(df_clean.values.tolist())
            print(f"🟢 成功附加 {len(df_clean)} 筆資料至 {sheet_name}")
    except Exception as e:
        print(f"❌ 寫入異常: {e}")

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json: return None
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return gspread.authorize(Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes))

def main():
    print("🚀 啟動五合一整合版台股分析與降維決策大腦 v7.1")
    SPREADSHEET_KEY = os.environ.get("SPREADSHEET_KEY")
    gc = get_gspread_client()

    full_report = f"📊 V14.1 萬檔市場融合競技戰報 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    full_report += "🏆 [決策中樞] 最優模型預測完成..."

    if gc and SPREADSHEET_KEY:
        print("\n準備寫入戰報至 PCA_PRE_FIN...")
        # 轉換文字成 Gspread 支援的矩陣格式
        matrix_data = [[line] for line in full_report.split('\n')]
        
        # 【修正點】: 安全覆寫矩陣戰報
        safe_gspread_write(gc, SPREADSHEET_KEY, "PCA_PRE_FIN", matrix_data=matrix_data)
        
        # 寫入 5in1
        log_df = pd.DataFrame({"Time": [datetime.now().strftime('%Y-%m-%d %H:%M:%S')], "Status": ["Success"]})
        safe_gspread_write(gc, SPREADSHEET_KEY, "5in1", log_df, mode="append")

if __name__ == "__main__":
    main()
