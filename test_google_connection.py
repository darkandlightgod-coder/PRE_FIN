# -*- coding: utf-8 -*-
"""
Google Sheets 寫入功能最終連線測試 (針對 5in1)
=========================================================
目的：驗證 GitHub Actions / 本地端 是否擁有完整權限，
      並測試寫入「到此一遊」至目標 Sheet (5in1)。
"""

import os
import sys
import json
from datetime import datetime
import subprocess
import importlib

# ==========================================
# 【環境自檢】確保套件存在
# ==========================================
def bootstrap():
    dependencies = ["gspread", "google-auth", "google-api-python-client"]
    for package in dependencies:
        try:
            if package == "google-auth": importlib.import_module("google.oauth2")
            elif package == "google-api-python-client": importlib.import_module("googleapiclient")
            else: importlib.import_module(package)
        except ImportError:
            print(f"📦 正在安裝測試套件: {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

bootstrap()

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==========================================
# 【核心測試邏輯】
# ==========================================
def main():
    print("\n" + "="*50)
    print("🚀 [連線測試啟動] 準備寫入 '5in1'")
    print("="*50)
    
    # 1. 抓取環境變數
    creds_json_str = os.environ.get("GSPREAD_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    target_sheet_name = "5in1"
    
    if not creds_json_str:
        print("❌ 失敗：找不到環境變數 `GSPREAD_CREDENTIALS`，請檢查金鑰設定。")
        sys.exit(1)
        
    try:
        # 2. 驗證與授權
        print("🔑 正在驗證 Google API 金鑰...")
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = json.loads(creds_json_str)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        print("✅ 憑證授權成功！")

        # 3. 尋找或建立 5in1 檔案
        print(f"🔍 正在尋找或建立雲端試算表：[{target_sheet_name}]...")
        sh = None
        if folder_id:
            query = f"'{folder_id}' in parents and name='{target_sheet_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            items = results.get('files', [])
            if items:
                print(f"   ↳ 找到已存在的 [{target_sheet_name}] (ID: {items[0]['id']})")
                sh = gc.open_by_key(items[0]['id'])
            else:
                print(f"   ↳ 找不到檔案，正在指定的資料夾 (ID: {folder_id}) 內建立新檔案...")
                sh = gc.create(target_sheet_name, folder_id=folder_id)
        else:
            print("   ⚠️ 警告：未設定 GOOGLE_DRIVE_FOLDER_ID，將在根目錄尋找或建立...")
            try: sh = gc.open(target_sheet_name)
            except: sh = gc.create(target_sheet_name)
            
        # 4. 執行寫入測試
        print("📝 準備寫入測試數據...")
        wks = sh.sheet1
        wks.clear() # 清空原本內容
        
        # 準備寫入的內容
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        test_content = [
            ["========================================"],
            [f"🎉 到此一遊！"],
            [f"🕒 寫入時間：{current_time}"],
            ["✅ 系統寫入權限測試：完美通過"],
            ["========================================"]
        ]
        
        wks.update("A1", test_content)
        
        # 測試格式化
        wks.format("A1:A5", {"textFormat": {"fontFamily": "Courier New", "fontSize": 12, "bold": True}})
        
        print(f"🎉 測試大成功！請去 Google Drive 查看 [{target_sheet_name}] 檔案是否出現「到此一遊」！")

    except Exception as e:
        print(f"\n❌ 測試發生不可預期的錯誤：{str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
