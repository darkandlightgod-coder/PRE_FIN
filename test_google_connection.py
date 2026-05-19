# -*- coding: utf-8 -*-
"""
Google Drive / Sheet 連線極簡測試程式
只做三件事：
1. 讀取環境變數。
2. 登入 Google API 並印出 Service Account Email。
3. 在指定的 Drive 資料夾內，建立一個全新的空白試算表。
"""

import os
import sys
import json
import random
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

def main():
    print("=" * 50)
    print("🔍 開始執行 Google Drive 連線極簡測試...")
    print("=" * 50)

    # 1. 抓取環境變數
    creds_json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not creds_json_str:
        print("❌ 錯誤：找不到環境變數 GOOGLE_SERVICE_ACCOUNT_JSON，請檢查 GitHub Secrets。")
        sys.exit(1)
    if not folder_id:
        print("❌ 錯誤：找不到環境變數 GOOGLE_DRIVE_FOLDER_ID，請檢查 GitHub Secrets。")
        sys.exit(1)

    # 2. 解析憑證並印出重要資訊
    try:
        creds_dict = json.loads(creds_json_str)
        client_email = creds_dict.get("client_email", "無法解析 Email")
        print("✅ 成功解析 JSON 憑證！")
        print(f"🤖 機器人 (Service Account) Email: {client_email}")
        print(f"📁 目標資料夾 ID: {folder_id}")
        print("-" * 50)
        print("⚠️ 【通關密語檢查】")
        print(f"請務必確認您已經把您的 Google Drive 資料夾，共用並給予「編輯者」權限給：")
        print(f"👉 {client_email}")
        print("-" * 50)
    except Exception as e:
        print(f"❌ 解析 JSON 憑證失敗，請檢查 Secret 內容是否為完整的 JSON 格式: {e}")
        sys.exit(1)

    # 3. 綁定 Google Auth
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        print("✅ 成功取得 Google API 授權！")
    except Exception as e:
        print(f"❌ Google 登入失敗: {e}")
        sys.exit(1)

    # 4. 測試在指定資料夾建立檔案
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet_name = f"Test_Sheet_{timestamp}"
    
    print(f"\n📝 準備在資料夾 {folder_id} 建立空白 Sheet: [{sheet_name}]...")
    try:
        # 使用 gspread 的 create 並直接指定 folder_id
        sh = gc.create(sheet_name, folder_id=folder_id)
        
        # 簡單寫入幾個字測試
        sh.sheet1.update("A1", [["連線測試成功！", f"建立時間: {timestamp}"]])
        
        print("🎉 建立與寫入大成功！")
        print(f"🔗 檔案網址: {sh.url}")
        print("👉 現在您可以點擊上面的網址，或者去您的 Google Drive 資料夾看看有沒有出現這個檔案！")
        
    except gspread.exceptions.APIError as api_error:
        print(f"\n❌ Google API 拒絕了請求！")
        print(f"詳細錯誤訊息: {api_error}")
        print("\n💡 【診斷建議】")
        print("1. 99% 的機率是：機器人帳號沒有該資料夾的「編輯權限」。請回到您的 Google Drive，對著該資料夾按右鍵 -> 共用 -> 貼上機器的 Email 並設為編輯者。")
        print("2. 確保 Folder ID 填寫正確 (網址列 folders/ 後面的那串亂碼)。")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 建立 Sheet 發生未知錯誤: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
