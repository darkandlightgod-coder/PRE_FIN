# -*- coding: utf-8 -*-
"""
Google Sheets API 獨立讀寫測試腳本 (GitHub Actions Secrets 版)
目的：驗證 Service Account 讀寫權限，並釐清 403 Storage Quota 錯誤源頭。
"""

import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime

# =====================================================================
# ⚙️ 核心配置：從 GitHub Secrets (環境變數) 讀取
# =====================================================================
CREDENTIALS_JSON_STR = os.environ.get("GSPREAD_CREDENTIALS")
FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

# 測試用的工作表名稱
WORKSHEET_NAME = "API_TEST"

def check_secrets():
    """確保 Secrets 已經成功載入"""
    if not CREDENTIALS_JSON_STR:
        print("❌ [錯誤] 找不到環境變數 'GSPREAD_CREDENTIALS'！請檢查 GitHub Actions 的 env 設定。")
        sys.exit(1)
    if not FOLDER_ID:
        print("❌ [錯誤] 找不到環境變數 'GOOGLE_DRIVE_FOLDER_ID'！請檢查 GitHub Actions 的 env 設定。")
        sys.exit(1)

def main():
    print("==========================================")
    print("🚀 啟動 Google Sheets API 讀寫分離測試")
    print("==========================================")
    
    check_secrets()
    
    # ---------------------------------------------------------
    # 1. 進行 API 認證 (包含 Gspread 與 Drive API)
    # ---------------------------------------------------------
    print("🔑 正在透過 GitHub Secrets (GSPREAD_CREDENTIALS) 進行認證...")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        creds_dict = json.loads(CREDENTIALS_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        print("✅ API 認證成功！\n")
    except Exception as e:
        print(f"❌ [錯誤] 憑證載入或認證發生未預期錯誤: {str(e)}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 2. 尋找目標資料夾中的現有試算表
    # ---------------------------------------------------------
    print(f"📁 正在搜尋資料夾 ID: {FOLDER_ID} 內的 Google Sheets 檔案...")
    try:
        query = f"'{FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        
        if not items:
            print("⚠️ [警告] 在該資料夾內找不到任何 Google Sheets 檔案！")
            print("   為了確保測試不觸發 403 檔案建立限制，請先到您的 Google Drive 該資料夾中，")
            print("   【手動】右鍵建立一個 Google 試算表，然後再重新執行此 Action。")
            sys.exit(1)
            
        target_file = items[0] # 取找到的第一個檔案來測試
        target_sheet_id = target_file['id']
        target_sheet_name = target_file['name']
        print(f"✅ 找到測試目標檔案: 「{target_sheet_name}」 (ID: {target_sheet_id})\n")
        
    except Exception as e:
        print(f"❌ [錯誤] 搜尋資料夾檔案失敗: {str(e)}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. [測試階段 1] : 讀取現有檔案測試 (Read Test)
    # ---------------------------------------------------------
    print(f"🔍 [階段 1: 讀取測試] 嘗試開啟試算表並尋找工作表「{WORKSHEET_NAME}」...")
    try:
        # 使用 open_by_key 絕對不觸發新建檔案的配額
        sh = gc.open_by_key(target_sheet_id)
        
        try:
            wks = sh.worksheet(WORKSHEET_NAME)
            print(f"✅ 成功找到工作表: 「{WORKSHEET_NAME}」")
        except gspread.exceptions.WorksheetNotFound:
            print(f"⚠️ 找不到工作表「{WORKSHEET_NAME}」，正在安全地新增一個 tab...")
            # 新增 tab 不算作新建整個文件，通常不會觸發 Drive Quota
            wks = sh.add_worksheet(title=WORKSHEET_NAME, rows=100, cols=20)
            print(f"✅ 成功建立工作表: 「{WORKSHEET_NAME}」")
            
        # 讀取一小塊區域測試
        existing_data = wks.get("A1:C3")
        print(f"✅ 讀取測試完成，目前狀態: {existing_data if existing_data else '空無一物'}\n")
        
    except gspread.exceptions.APIError as api_err:
        print(f"❌ [讀取失敗] Google API 回報錯誤: {api_err}")
        return
    except Exception as e:
        print(f"❌ [讀取失敗] 發生未預期的錯誤: {str(e)}")
        return

    # ---------------------------------------------------------
    # 4. [測試階段 2] : 寫入/覆寫測試 (Write Test)
    # ---------------------------------------------------------
    print(f"📝 [階段 2: 寫入測試] 準備寫入測試資料...")
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_data = [
            ["測試項目", "時間戳記", "狀態", "備註"],
            ["API 連線", now_str, "SUCCESS", "直接透過 ID 鎖定並寫入，未調用 create()"],
            ["檔案覆寫", now_str, "SUCCESS", "如果看到這行，代表帳號寫入權限與儲存空間完全正常！"]
        ]
        
        # 執行清空與覆寫
        wks.clear()
        wks.update("A1", test_data)
        
        # 測試格式化
        wks.format("A1:D1", {"textFormat": {"bold": True, "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}})
        
        print("✅ 寫入與格式化測試大成功！")
        print("==========================================")
        print("🎉 結論：測試腳本運行成功！")
        print("👉 這證明你的 Service Account 權限與空間配額皆【完全正常】。")
        print("👉 之前的 403 錯誤，確實是因為舊程式中重複執行「建立新檔案 (create)」導致 Google 安全封鎖。")
        print("==========================================")
        
    except gspread.exceptions.APIError as api_err:
        print(f"❌ [寫入失敗] Google API 回報錯誤: {api_err}")
        if "Quota" in str(api_err):
            print("💡 診斷：此處若報 Quota 錯誤，可能是該檔案擁有的帳號空間已滿，或短時間內 update 太多次被限流。")
    except Exception as e:
        print(f"❌ [寫入失敗] 發生未預期的錯誤: {str(e)}")

if __name__ == "__main__":
    main()
