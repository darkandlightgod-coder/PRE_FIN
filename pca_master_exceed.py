# -*- coding: utf-8 -*-
"""
V10.0 - 總控樞紐 (Master Orchestrator)
功能: 依序執行 5 個子模組，攔截並印出所有可能導致中斷的嚴重錯誤。
"""
import subprocess
import sys
import time

MODULES = [
    "GLOBAL_Market_Factors_v10.py",
    "specific_web_index_and_all_number_data_grab_v10.py",
    "web_grab_and_language_AI_score_for_PCA_v10.py",
    "specific_stock_chips_scraper_v10.py",
    "PCA_TWII_v10.py"
]

def main():
    print("="*60)
    print("🌌 PCA 神諭矩陣 V10.0 (Oracle Matrix) 總控台啟動")
    print("="*60)
    
    for mod in MODULES:
        print(f"\n▶️ 準備執行子節點: {mod}")
        try:
            result = subprocess.run([sys.executable, mod], check=True, text=True)
            time.sleep(2) # 節點冷卻，避免 API Rate Limit
        except subprocess.CalledProcessError as e:
            print(f"❌ 節點 {mod} 執行失敗，回傳碼: {e.returncode}")
            print(f"   錯誤細節請參考上方輸出日誌。")
            # 繼續執行下一個，具備容錯能力
        except Exception as e:
            print(f"❌ 總控台發生意外崩潰: {e}")

    print("\n🎉 V10.0 總排程執行完畢！")

if __name__ == "__main__":
    main()
