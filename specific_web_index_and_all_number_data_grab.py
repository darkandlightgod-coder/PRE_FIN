# -*- coding: utf-8 -*-
import os
import glob
import pandas as pd

def diagnose_csv_files():
    print("===========================================")
    print("🕵️ 啟動台股 CSV 本地讀取探測器 (Debug 模式)")
    print("===========================================")
    
    # 1. 列出當前目錄下所有的 CSV
    all_csvs = glob.glob("*.csv")
    if not all_csvs:
        print("❌ 錯誤：在目前的目錄中找不到任何 .csv 結尾的檔案！")
        return
        
    print(f"📂 目前目錄下共有 {len(all_csvs)} 個 CSV 檔案: {all_csvs}")
    
    # 篩選我們可能需要的檔案
    target_files = [f for f in all_csvs if "上市" in f or "上櫃" in f or "興櫃" in f or "公司" in f]
    
    if not target_files:
        print("⚠️ 找不到名稱包含「上市、上櫃、興櫃、公司」的 CSV，我們將強制讀取所有 CSV 檔案。")
        target_files = all_csvs
    else:
        print(f"🎯 鎖定目標 CSV 檔案: {target_files}")

    all_stock_codes = set()

    # 2. 逐一讀取並探測內容
    for file in target_files:
        print(f"\n▶️ 正在解析檔案: {file}")
        
        df = None
        # 台灣政府/券商的資料常見這幾種編碼，輪流嘗試直到成功
        encodings_to_try = ['utf-8-sig', 'big5', 'utf-8', 'cp950']
        
        for enc in encodings_to_try:
            try:
                # 統一以字串格式讀取，避免代號前面的 0 被吃掉，或被當成數字導致出錯
                df = pd.read_csv(file, encoding=enc, dtype=str)
                print(f"   ✅ 成功以 [{enc}] 編碼讀取檔案！")
                break
            except Exception as e:
                pass
                
        if df is None:
            print(f"   ❌ 嚴重錯誤：無法使用任何已知編碼讀取 {file}。檔案可能損毀或非純文字 CSV。")
            continue
            
        # 清除欄位名稱前後的隱藏空白字元 (例如 ' 公司代號 ' 變成 '公司代號')
        original_columns = list(df.columns)
        df.columns = df.columns.str.strip()
        print(f"   📊 檔案內所有欄位名稱: {original_columns}")
        
        # 3. 尋找「代號」或「代碼」欄位
        code_col = next((col for col in df.columns if '代號' in col or '代碼' in col), None)
        
        if code_col:
            print(f"   🎯 成功鎖定代號欄位：'{code_col}'")
        else:
            code_col = df.columns[0]
            print(f"   ⚠️ 找不到名稱包含代號的欄位，強制使用第一欄：'{code_col}'")
            
        # 4. 提取資料並過濾 (只保留 4 碼純數字)
        raw_codes = df[code_col].astype(str).str.strip()
        # 正規表達式：過濾出開頭到結尾都是數字，且長度為 4 的字串
        valid_codes = raw_codes[raw_codes.str.match(r'^\d{4}$', na=False)].tolist()
        
        print(f"   📦 成功從此檔案提取 {len(valid_codes)} 檔有效的四碼股票代號。")
        all_stock_codes.update(valid_codes)

    # 5. 總結印出
    final_list = sorted(list(all_stock_codes))
    print("\n===========================================")
    print(f"🎉 總結：合併去重複後，共獲取 {len(final_list)} 檔股票代號！")
    print("===========================================")
    
    if final_list:
        print("📜 完整代號清單預覽：")
        # 每 15 個印一行，版面比較乾淨
        for i in range(0, len(final_list), 15):
            print(", ".join(final_list[i:i+15]))
    else:
        print("❌ 最終未能獲取任何股票代號，請檢查 CSV 內容結構！")

if __name__ == "__main__":
    diagnose_csv_files()
