# -*- coding: utf-8 -*-
"""
Google Sheets API 獨立讀寫測試腳本 (不含檔案建立邏輯)
目的：驗證 Service Account 是否能正常連線，並釐清 403 Storage Quota 錯誤源頭。
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# =====================================================================
# ⚙️ 測試配置區 (請務必填寫這裡的參數)
# =====================================================================

# 1. 填入你剛才手動建立/挑選的 Google Sheet ID (不要填網址，只要 ID)
SPREADSHEET_KEY = "請將這裡替換成你的_Google_Sheet_ID"

# 2. 測試用的工作表名稱 (建議手動在試算表裡建好這個名稱的 Tab)
WORKSHEET_NAME = "API_TEST"

# 3. 憑證檔案路徑 (預設讀取同目錄下的 credentials.json，或讀取環境變數)
CREDENTIALS_FILE = "credentials.json" 

# =====================================================================

def get_google_client():
    """初始化並獲取 gspread client"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # 優先嘗試從 GitHub Actions 常用的環境變數讀取
    if "GCP_CREDENTIALS" in os.environ:
        print("🔑 偵測到環境變數 GCP_CREDENTIALS，以此進行登入...")
        creds_dict = json.loads(os.environ["GCP_CREDENTIALS"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    # 否則嘗試讀取實體檔案
    elif os.path.exists(CREDENTIALS_FILE):
        print(f"🔑 偵測到本地檔案 {CREDENTIALS_FILE}，以此進行登入...")
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    else:
        raise FileNotFoundError("找不到憑證！請設定 GCP_CREDENTIALS 環境變數或提供 credentials.json 檔案。")
        
    return gspread.authorize(creds)

def test_read_write():
    print("==========================================")
    print("🚀 啟動 Google Sheets API 讀寫分離測試")
    print("==========================================")
    
    try:
        gc = get_google_client()
        print("✅ API 認證成功！\n")
    except Exception as e:
        print(f"❌ API 認證失敗: {str(e)}")
        return

    # ---------------------------------------------------------
    # [測試階段 1] : 讀取現有檔案測試 (Read Test)
    # ---------------------------------------------------------
    print(f"🔍 [階段 1: 讀取測試] 嘗試開啟試算表 ID: {SPREADSHEET_KEY}")
    try:
        # 使用 open_by_key 直接鎖定檔案，絕對不觸發 create()
        sh = gc.open_by_key(SPREADSHEET_KEY)
        print(f"✅ 成功連接試算表！檔案標題為: 「{sh.title}」")
        
        # 嘗試獲取 Worksheet
        try:
            wks = sh.worksheet(WORKSHEET_NAME)
            print(f"✅ 成功找到工作表: 「{WORKSHEET_NAME}」")
        except gspread.exceptions.WorksheetNotFound:
            print(f"⚠️ 找不到工作表「{WORKSHEET_NAME}」！")
            print(f"   為了維持環境純淨不觸發配額，請手動打開試算表建立一個名為 '{WORKSHEET_NAME}' 的工作表後再試。")
            return
            
        # 讀取一小塊區域測試
        existing_data = wks.get("A1:C3")
        print(f"✅ 讀取測試完成，目前前三列資料狀態: {existing_data if existing_data else '空無一物'}\n")
        
    except gspread.exceptions.APIError as api_err:
        print(f"❌ [讀取失敗] Google API 回報錯誤: {api_err}")
        return
    except Exception as e:
        print(f"❌ [讀取失敗] 發生未預期的錯誤: {str(e)}")
        return

    # ---------------------------------------------------------
    # [測試階段 2] : 寫入/覆寫測試 (Write Test)
    # ---------------------------------------------------------
    print(f"📝 [階段 2: 寫入測試] 準備向工作表「{WORKSHEET_NAME}」寫入測試資料...")
    try:
        # 準備一些帶有時間戳記的假資料
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_data = [
            ["測試項目", "時間戳記", "狀態", "備註"],
            ["API 連線", now_str, "SUCCESS", "這是一筆直接透過 ID 鎖定並寫入的資料"],
            ["檔案覆寫", now_str, "SUCCESS", "如果不報 403 錯誤，代表你的帳號寫入權限完全正常！"]
        ]
        
        # 執行清空與覆寫 (這會測試更新配額)
        wks.clear()
        wks.update("A1", test_data)
        
        # 順便測試一下格式化功能
        wks.format("A1:D1", {"textFormat": {"bold": True, "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}})
        
        print("✅ 寫入與格式化測試大成功！請前往你的 Google Sheet 查看結果。")
        print("==========================================")
        print("🎉 結論：如果這支程式執行成功，代表你的帳號容量、權限、API 皆完全正常。")
        print("         之前的 403 錯誤【100%】是因為舊程式邏輯狂開新檔案 (gc.create) 導致觸發防護。")
        print("==========================================")
        
    except gspread.exceptions.APIError as api_err:
        print(f"❌ [寫入失敗] Google API 回報錯誤: {api_err}")
        if "Quota" in str(api_err):
            print("💡 診斷：這裡如果報 Quota 錯誤，可能是該檔案所在資料夾的擁有者空間已滿，或是短時間內 update 太多次被限流。")
    except Exception as e:
        print(f"❌ [寫入失敗] 發生未預期的錯誤: {str(e)}")

if __name__ == "__main__":
    test_read_write()
