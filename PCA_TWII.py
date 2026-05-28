# -*- coding: utf-8 -*-
"""
V14.6 PLS 監督式降維引擎 (多核心極速版)
特色:
1. 演算法升級：從無監督的 PCA 升級為監督式的 PLS (偏最小平方法)，降維時會參考目標 y。
2. 防未來數據洩漏：嚴格執行 Train/Test 切分後再進行 PLS Fit。
3. 極速優化：導入 ProcessPoolExecutor，多檔股票平行運算。
"""
import os
import pandas as pd
import numpy as np
import traceback
from datetime import datetime
from sklearn.cross_decomposition import PLSRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error
from xgboost import XGBRegressor
import concurrent.futures

# ==========================================
# 參數設定
# ==========================================
N_COMPONENTS = 10     # PLS 要降成幾個特徵 (等同於之前的 PCA 數量)
TRAIN_RATIO = 0.8     # 80% 資料作為訓練集(Train)，20% 作為測試集(Test)

# 預測維度設定 (天數)
PREDICT_HORIZONS = {
    '1day': 1,
    '7day': 7,
    '1month': 22,   # 交易日
    '6month': 126   # 交易日
}

def process_single_target(target_name, df_X, series_y):
    """
    這是一個獨立的工作單元，設計成可以在多核心下平行執行。
    負責：特徵對齊 -> Train/Test 切分 -> PLS 降維 -> XGBoost 預測。
    """
    print(f"啟動平行運算: 處理標的 [{target_name}] ...")
    results = {'Target': target_name}
    
    try:
        # 1. 對齊 X 和 y 的日期 (只保留兩者都有資料的日子)
        df_merged = pd.concat([df_X, series_y.rename('Target_Y')], axis=1).dropna()
        X_aligned = df_merged.drop(columns=['Target_Y']).values
        y_aligned = df_merged['Target_Y'].values
        
        # 取得最後一天的特徵，用來預測「真正的未來」
        X_latest_unscaled = X_aligned[-1].reshape(1, -1)
        
        for horizon_name, shift_days in PREDICT_HORIZONS.items():
            # 2. 建立預測目標 (將 y 往上推 shift_days 天)
            # 例如預測 7 天後，今天的 X 要對應到 7 天後的 y
            y_horizon = pd.Series(y_aligned).shift(-shift_days).values
            
            # 剔除最後因為 shift 產生 NaN 的天數
            valid_idx = ~np.isnan(y_horizon)
            X_valid = X_aligned[valid_idx]
            y_valid = y_horizon[valid_idx]
            
            if len(X_valid) < 100:
                continue # 資料太少，跳過
                
            # 3. 嚴格的時間切分 (Time-Series Split)
            # 絕對不能用 random_state 隨機切分，否則會用未來的資料預測過去！
            split_idx = int(len(X_valid) * TRAIN_RATIO)
            X_train, X_test = X_valid[:split_idx], X_valid[split_idx:]
            y_train, y_test = y_valid[:split_idx], y_valid[split_idx:]
            
            # 4. 特徵縮放 (只能 Fit 在 Train Set)
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            X_latest_scaled = scaler.transform(X_latest_unscaled) # 今天的最新數據
            
            # 5. 🔥 核心升級：PLS 監督式降維 🔥
            # PLS 會偷看 y_train，找出 X 中最能解釋 y 的方向
            n_comp = min(N_COMPONENTS, X_train_scaled.shape[1])
            pls = PLSRegression(n_components=n_comp)
            
            X_train_pls = pls.fit_transform(X_train_scaled, y_train)[0]
            X_test_pls = pls.transform(X_test_scaled)
            X_latest_pls = pls.transform(X_latest_scaled)
            
            # 6. XGBoost 訓練與預測
            model = XGBRegressor(n_estimators=100, learning_rate=0.05, n_jobs=1, random_state=42)
            model.fit(X_train_pls, y_train)
            
            # 測試集驗證 (RMSE)
            test_preds = model.predict(X_test_pls)
            rmse = np.sqrt(mean_squared_error(y_test, test_preds))
            
            # 預測未來真實股價 (拿最後一天的特徵去預測)
            future_pred = model.predict(X_latest_pls)[0]
            current_price = y_aligned[-1]
            pred_return_pct = ((future_pred - current_price) / current_price) * 100
            
            # 儲存結果
            results[f"{horizon_name}_RMSE"] = round(rmse, 2)
            results[f"{horizon_name}_Pred_Price"] = round(future_pred, 2)
            results[f"{horizon_name}_Pred_Return(%)"] = round(pred_return_pct, 2)
            
        results['Status'] = "Success"
        
    except Exception as e:
        results['Status'] = "Failed"
        results['Error'] = str(e)
        
    return results

def run_pls_pipeline(df_X_master, dict_y_targets):
    """
    主控制程式：負責派發工作給多個 CPU 核心
    df_X_master: 所有的總經與市場特徵 DataFrame (Index為日期)
    dict_y_targets: 字典格式 {'2330.TW': Series, 'NVDA': Series, ...}
    """
    print(f"🚀 啟動 V14.6 PLS 分析引擎，共有 {len(dict_y_targets)} 檔標的等待處理。")
    final_results = []
    
    # 🔥 核心優化：使用 ProcessPoolExecutor 進行多進程平行運算
    # max_workers 預設會根據伺服器的 CPU 核心數自動分配
    with concurrent.futures.ProcessPoolExecutor() as executor:
        # 將工作打包並派發
        future_to_target = {
            executor.submit(process_single_target, target_name, df_X_master, series_y): target_name 
            for target_name, series_y in dict_y_targets.items()
        }
        
        # 收集平行運算完畢的結果
        for future in concurrent.futures.as_completed(future_to_target):
            target_name = future_to_target[future]
            try:
                res = future.result()
                final_results.append(res)
                print(f"✅ [{target_name}] 計算完成！")
            except Exception as e:
                print(f"❌ [{target_name}] 發生嚴重崩潰: {str(e)}")
                traceback.print_exc()

    # 將結果轉為 DataFrame 方便後續寫入 Google Sheet
    df_output = pd.DataFrame(final_results)
    df_output['Update_Time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df_output

# ==========================================
# 模擬執行區 (供您參考如何呼叫)
# ==========================================
if __name__ == "__main__":
    # 這裡假設您已經從 Google Sheet 抓下了 X (總經) 與 y (個股) 的資料
    # df_X_master = ... 
    # dict_y_targets = {'2330.TW': df_2330['Close'], 'NVDA': df_nvda['Close']}
    
    # df_final_results = run_pls_pipeline(df_X_master, dict_y_targets)
    # 接著就可以呼叫您原本的 safe_gspread_write(..., df_final_results, mode="clear_update")
    pass
