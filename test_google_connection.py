# -*- coding: utf-8 -*-
"""
Google Drive / Sheet 連線極簡測試程式
針對 GSPREAD_CREDENTIALS 變數名優化版
"""

import os
import sys
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

def main():
    print("=" * 50)
    print("🔍 開始執行 Google Drive 連線極簡測試...")
    print("=" * 50)

    # 1. 精準抓取您所設定的環境變數
    creds_json_str = os.environ.get("GSPREAD_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not creds_json_str:
        print("❌ 致命錯誤：找不到環境變數 GSPREAD_CREDENTIALS！")
        print("請檢查 GitHub Actions 的 yml 檔案中的 env 區塊是否有正確映射。")
        sys.exit(1)
    if not folder_id:
        print("❌ 致命錯誤：找不到環境變數 GOOGLE_DRIVE_FOLDER_ID！")
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
        print("✅ 成功取得 Google API 授權！準備執行寫入測試...")
    except Exception as e:
        print(f"❌ Google API 授權失敗: {e}")
        sys.exit(1)

    # 4. 測試在指定資料夾建立檔案
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet_name = f"Connection_Test_{timestamp}"
    
    print(f"\n📝 準備在您的資料夾中建立空白 Sheet: [{sheet_name}]...")
    try:
        # 使用 folder_id 參數建立
        sh = gc.create(sheet_name, folder_id=folder_id)
        
        # 簡單寫入幾個字測試
        sh.sheet1.update("A1", [["連線測試大成功！", f"建立時間: {timestamp}"]])
        
        print("🎉 建立與寫入大成功！")
        print(f"🔗 檔案網址: {sh.url}")
        print("👉 測試通過！您的機器人已具有寫入權限，請將 yml 換回正式主程式！")
        
    except gspread.exceptions.APIError as api_error:
        print(f"\n❌ Google API 拒絕了請求！")
        print(f"詳細錯誤訊息: {api_error}")
        print("\n💡 【最可能的原因】")
        print(f"機器人 ({client_email}) 沒有該資料夾的「編輯權限」。請至 Google Drive 設定共用！")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 發生未知錯誤: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
