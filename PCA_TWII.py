# -*- coding: utf-8 -*-
"""
V14.0 PCA_TWII.py (終極三維特徵融合 + 報錯透明化 + 極致囉嗦追蹤版)
- 雷達追蹤：在 PCA、機器學習模型 (RF, XGB, Ridge) 訓練的每個迴圈加入詳細 print，讓 Github Action 有心跳日誌。
- 保留警告：應要求退回 DataFrame replace("") 語法，保留 FutureWarning 作為運行指標。
- 致命錯誤透明化：保留完整的 traceback 印出，絕不默默卡死。
"""
import os
import sys
import subprocess
import importlib
from datetime import datetime
import json
import time
import traceback
import re
import pandas as pd
import numpy as np

# --- 參數設定 ---
TARGET_SPREADSHEETS = {
    "PRE_TWII": "",         
    "PRE_台積電(2330)": "",
    "PRE_聯電(2303)": "",
    "PRE_英業達(2356)": "",
    "PRE_中鋼(2002)": "",
    "PRE_NVIDIA(NVDA)": "",
    "PRE_TESLA(TSLA)": "",
    "PRE_INTEL(INTC)": "",
    "PRE_Apple(AAPL)": "",
    "PRE_Microsoft(MSFT)": "",
    "PRE_Amazon(AMZN)": "",
    "PRE_Eli Lilly(LLY)": "",
    "PRE_Novo Nordisk(NVO)": "",
    "PRE_Toyota(7203.T)": ""
}

def bootstrap():
    print(f"🛠️ [{datetime.now().strftime('%H:%M:%S')}] 啟動環境檢查...")
    dependencies = {
        "pandas": "pandas", "numpy": "numpy", "sklearn": "scikit-learn",
        "xgboost": "xgboost", "gspread": "gspread", "google.oauth2.service_account": "google-auth"
    }
    installed_any = False
    for module, package in dependencies.items():
        try:
            importlib.import_module(module)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            installed_any = True
    if installed_any:
        importlib.invalidate_caches()

bootstrap()

from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from xgboost import XGBRegressor
import gspread
from google.oauth2.service_account import Credentials

WINDOWS = {"3day": 3, "7day": 7, "1month": 22, "1year": 252}

def get_gspread_client():
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(creds)

def safe_gspread_write(gc, sp_id, tab_name, df, mode="append"):
    for attempt in range(3):
        try:
            print(f"      📝 [API 進度] 準備寫入 Google Sheet (ID: {sp_id[:10]}...), 嘗試次數: {attempt+1}/3")
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                print(f"      🆕 [API 進度] 找不到分頁 '{tab_name}'，正在建立新分頁...")
                worksheet = sh.add_worksheet(title=tab_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            # 清洗以符合 JSON 格式
            df = df.replace([np.inf, -np.inf], np.nan).fillna("")
            new_headers = df.columns.values.tolist()
            
            if mode == "clear_update":
                print(f"      🧹 [API 進度] 清空舊資料並準備更新 {len(df)} 筆新資料...")
                data = [new_headers] + df.values.tolist()
                worksheet.clear()
                worksheet.update(values=data, range_name=None)
            elif mode == "append":
                existing_data = worksheet.get_all_values()
                if not existing_data:
                    worksheet.append_row(new_headers)
                elif existing_data[0] != new_headers:
                    worksheet.clear()
                    worksheet.append_row(new_headers)
                worksheet.append_rows(df.values.tolist())
            print(f"      ✅ [API 進度] 寫入成功！")
            return True
        except gspread.exceptions.APIError as e:
            print(f"      ⚠️ [API 警告] Google API 忙線 (錯誤碼: {e.response.status_code if hasattr(e, 'response') else 'N/A'})，等待 3 秒... ({attempt+1}/3)")
            time.sleep(3)
        except Exception as e:
            print(f"      ❌ [API 致命錯誤] 寫入發生非預期錯誤:")
            traceback.print_exc()
            time.sleep(2)
    return False

def append_error_note(gc, sp_id, tab_name, error_msg):
    for attempt in range(3):
        try:
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=tab_name, rows="50", cols="10")
            worksheet.append_row([error_msg])
            return True
        except Exception as e:
            print(f"   ❌ 寫入錯誤備註時發生錯誤:")
            traceback.print_exc()
            time.sleep(2)
    return False

def load_sheet_as_dataframe(sh, worksheet_name=None):
    try:
        if worksheet_name:
            ws = sh.worksheet(worksheet_name)
        else:
            ws = sh.get_worksheet(0)
    except Exception as e:
        raise ValueError(f"找不到分頁: {worksheet_name if worksheet_name else '第一個分頁'}。錯誤: {e}")
        
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    
    if 'Date' not in df.columns:
        if '日期' in df.columns:
            df.rename(columns={'日期': 'Date'}, inplace=True)
        else:
            df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
    
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df.dropna(subset=['Date'], inplace=True)
    df.set_index('Date', inplace=True)
    
    # 🌟 退回原本的語法，保留 FutureWarning 讓您知道它正在運行
    print(f"      👉 [資料處理] 正在進行 replace('') 與 to_numeric 轉換...")
    df = df.replace("", np.nan).apply(pd.to_numeric, errors='coerce').ffill()
    
    df.dropna(axis=1, how='all', inplace=True)
    df.sort_index(inplace=True)
    return df

def find_spreadsheet(gc, file_name, file_url=""):
    for attempt in range(3):
        try:
            if file_url.strip():
                try: 
                    return gc.open_by_url(file_url.strip())
                except Exception: 
                    pass
            return gc.open(file_name)
            
        except gspread.exceptions.SpreadsheetNotFound:
            return None
        except gspread.exceptions.APIError as e:
            if attempt < 2:
                print(f"   ⚠️ Google API 伺服器忙線中，等待 5 秒後自動重試... ({attempt+1}/3)")
                time.sleep(5)
            else:
                print(f"   ❌ 搜尋檔案時 Google API 持續無回應。")
                raise e
        except Exception as e:
            print(f"   ❌ 搜尋檔案時發生錯誤: {e}")
            if attempt < 2:
                time.sleep(3)
            else:
                raise e
    return None

def identify_target_column(df, file_name):
    candidates = []
    if "TWII" in file_name:
        candidates = ["^twii", "twii", "加權指數", "大盤"]
    else:
        match = re.search(r'PRE_(.*?)\((.*?)\)', file_name)
        if match:
            name = match.group(1).strip()
            ticker = match.group(2).strip()
            if name: candidates.append(name)
            if ticker: candidates.append(ticker)
        else:
            candidates.append(file_name.replace("PRE_", ""))
            
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and ("close" in col_lower or "收盤" in col_lower):
                return col
                
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in candidates:
            if cand.lower() in col_lower and "volume" not in col_lower and "成交量" not in col_lower:
                return col
    return None

def predict_with_layered_arena(df_X, s_y):
    print("      ⚙️ [模型進度] 啟動預測引擎 (predict_with_layered_arena)...")
    s_y.name = "Target_Close"
    aligned_data = pd.concat([df_X, s_y], axis=1, join='inner').dropna()
    
    if len(aligned_data) < 100: 
        print(f"      ⚠️ [模型警告] 對齊後資料筆數不足 100 筆 (僅 {len(aligned_data)} 筆)，跳過訓練。")
        return None, None
    
    print(f"      ⚙️ [模型進度] 資料對齊成功，共 {len(aligned_data)} 筆有效交易日。")
    y_raw = aligned_data["Target_Close"]
    df_aligned_X = aligned_data.drop(columns=["Target_Close"])
    
    # 防護無限大
    df_aligned_X = df_aligned_X.replace([np.inf, -np.inf], 0)
    
    print("      📏 [模型進度] 正在執行特徵縮放 (StandardScaler)...")
    scaler = StandardScaler()
    X_scaled_np = scaler.fit_transform(df_aligned_X)
    df_X_scaled = pd.DataFrame(X_scaled_np, index=df_aligned_X.index, columns=df_aligned_X.columns)
    
    n_comp = min(10, len(df_aligned_X.columns))
    print(f"      🧬 [模型進度] 正在執行 PCA 降維 (萃取 {n_comp} 個主成分)...")
    pca = PCA(n_components=n_comp) 
    X_pca_np = pca.fit_transform(X_scaled_np)
    df_X_pca = pd.DataFrame(X_pca_np, index=df_aligned_X.index, columns=[f"PC{i+1}" for i in range(pca.n_components_)])
    
    merged_for_shift = pd.concat([df_X_scaled, df_X_pca, y_raw], axis=1)

    model_names = ['PCA_Poly_Ridge', 'RandomForest', 'XGBoost']
    model_preds = {m: {} for m in model_names}
    model_rmse = {m: {} for m in model_names} 
    
    for window_name, shift_days in WINDOWS.items():
        print(f"      ⏱️ [訓練進度] ====== 開始訓練【{window_name} ({shift_days}天)】預測區間 ======")
        
        y_target = merged_for_shift["Target_Close"].pct_change(shift_days).shift(-shift_days) * 100
        y_target = y_target.replace([np.inf, -np.inf], np.nan)
        
        valid_idx = ~y_target.isna()
        
        if valid_idx.sum() < 60:
            print(f"         ⚠️ 無效天數過多 (剩餘 {valid_idx.sum()} 筆)，跳過此區間。")
            for m in model_names: 
                model_preds[m][window_name] = "N/A"
                model_rmse[m][window_name] = None
            continue
            
        X_raw_v = merged_for_shift[df_aligned_X.columns].values[valid_idx]
        X_pca_v = merged_for_shift[[f"PC{i+1}" for i in range(pca.n_components_)]].values[valid_idx]
        Y_v = y_target[valid_idx].values
        
        split_idx = int(len(Y_v) * 0.8)
        
        X_latest_raw = merged_for_shift[df_aligned_X.columns].values[-1].reshape(1, -1)
        X_latest_pca = merged_for_shift[[f"PC{i+1}" for i in range(pca.n_components_)]].values[-1].reshape(1, -1)
        
        # 1. Ridge
        print(f"         🧠 正在訓練: PCA_Poly_Ridge 模型...")
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_pca_poly = poly.fit_transform(X_pca_v[:split_idx])
        X_test_pca_poly = poly.transform(X_pca_v[split_idx:])
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train_pca_poly, Y_v[:split_idx])
        r_preds_test = ridge.predict(X_test_pca_poly)
        model_rmse['PCA_Poly_Ridge'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], r_preds_test)))
        model_preds['PCA_Poly_Ridge'][window_name] = round(float(ridge.predict(poly.transform(X_latest_pca))[0]), 2)
        
        # 2. RandomForest
        print(f"         🌲 正在訓練: RandomForest (隨機森林) 模型...")
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        rf_preds_test = rf.predict(X_raw_v[split_idx:])
        model_rmse['RandomForest'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], rf_preds_test)))
        model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_raw)[0]), 2)
        
        # 3. XGBoost
        print(f"         🚀 正在訓練: XGBoost (極限梯度提升) 模型...")
        xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror')
        xgb.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        xgb_preds_test = xgb.predict(X_raw_v[split_idx:])
        model_rmse['XGBoost'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], xgb_preds_test)))
        model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_raw)[0]), 2)

    print("      🏆 [模型進度] 本標的所有模型訓練完畢，正在結算排名...")
    layers = list(WINDOWS.keys()) + ['Overall']
    for m in model_names:
        valid_rmses = [rmse for w, rmse in model_rmse[m].items() if rmse is not None]
        model_rmse[m]['Overall'] = float(np.mean(valid_rmses)) if valid_rmses else None

    model_ranks = {m: {} for m in model_names}
    for layer in layers:
        sorted_models = sorted(model_names, key=lambda m: model_rmse[m].get(layer) if model_rmse[m].get(layer) is not None else 9999.99)
        for rank, m in enumerate(sorted_models, 1):
            model_ranks[m][layer] = rank

    results = {}
    for m in model_names:
        results[m] = {'Preds': model_preds[m], 'RMSE': model_rmse[m], 'Ranks': model_ranks[m]}
        
    return results, df_X_pca

def main():
    print("="*70)
    print("🏆 PCA x 機器學習 (終極三維特徵融合版 V14.0 極致追蹤版)")
    print("="*70)
    
    try:
        gc = get_gspread_client()
        
        print("\n步驟 1: 尋找並融合三大特徵池 (總經、期貨、AI輿情)...")
        
        df_global = pd.DataFrame()
        sh_global = find_spreadsheet(gc, "global_market_factors")
        if sh_global:
            df_global = load_sheet_as_dataframe(sh_global)
            print(f"   ✅ [總經] 載入成功，特徵數: {len(df_global.columns)}")
        else:
            raise ValueError("找不到核心檔案 'global_market_factors'！")

        df_taifex = pd.DataFrame()
        sh_taifex = find_spreadsheet(gc, "taifex_derivatives_history")
        if sh_taifex:
            df_taifex = load_sheet_as_dataframe(sh_taifex)
            print(f"   ✅ [期貨] 載入成功，特徵數: {len(df_taifex.columns)}")

        df_ai = pd.DataFrame()
        sh_ai = find_spreadsheet(gc, "stock_history_AI_SCORE")
        if sh_ai:
            df_ai = load_sheet_as_dataframe(sh_ai)
            print(f"   ✅ [輿情] 載入成功，特徵數: {len(df_ai.columns)}")

        print("   🔄 正在將三大特徵池進行外部合併 (Outer Join)...")
        df_X_master = df_global.copy()
        
        if not df_taifex.empty:
            cols_to_use = df_taifex.columns.difference(df_X_master.columns)
            df_X_master = df_X_master.join(df_taifex[cols_to_use], how='outer')
            
        if not df_ai.empty:
            cols_to_use = df_ai.columns.difference(df_X_master.columns)
            df_X_master = df_X_master.join(df_ai[cols_to_use], how='outer')

        # 確保融合後沒有無限大
        df_X_master = df_X_master.sort_index().ffill().fillna(0)
        df_X_master = df_X_master.replace([np.inf, -np.inf], 0)
        print(f"   🔥 終極特徵矩陣融合完畢！總特徵數: {len(df_X_master.columns)}, 總天數: {len(df_X_master)}")

        print("\n步驟 2: 尋找並載入個股歷史資料 (stock_history_13_targets)...")
        stock_sh = find_spreadsheet(gc, "stock_history_13_targets")
        if not stock_sh:
            raise ValueError("找不到個股目標檔案 'stock_history_13_targets'")
        df_stocks = load_sheet_as_dataframe(stock_sh)
        print(f"   ✅ 成功載入！目標股欄位數: {len(df_stocks.columns)}")

        print(f"\n🎯 步驟 3: 啟動特徵對齊與模型預測...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dot = datetime.now().strftime("%Y.%m.%d")
        first_run_pca = None
        lake_sh_id = sh_global.id 
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉👉👉 開始處理新標的: 【{file_name}】 👈👈👈")
            dest_sh = find_spreadsheet(gc, file_name, file_url)
            if not dest_sh:
                print(f"   ❌ 找不到寫入表 [{file_name}]，跳過。")
                continue
            
            try:
                df_X = df_X_master.copy() 
                
                if file_name == "PRE_TWII":
                    target_col = identify_target_column(df_X_master, file_name)
                    if not target_col:
                        msg = f"{today_dot}更新失敗：在總經表中找不到 TWII 欄位。"
                        print(f"   ⚠️ {msg}")
                        append_error_note(gc, dest_sh.id, "預測紀錄", msg)
                        continue
                    s_y = df_X_master[target_col].copy()
                else:
                    target_col = identify_target_column(df_stocks, file_name)
                    if not target_col:
                        msg = f"{today_dot}更新失敗：找不到 '{file_name}' 匹配欄位。"
                        print(f"   ⚠️ {msg}")
                        append_error_note(gc, dest_sh.id, "預測紀錄", msg)
                        continue
                    s_y = df_stocks[target_col].copy()
                    
                print(f"   🔍 準備餵給模型: 特徵矩陣(X) + 目標欄位({target_col})")
                
                result, df_pca_features = predict_with_layered_arena(df_X, s_y)
                
                if not result:
                    msg = f"{today_dot}更新失敗：資料對齊後有效天數不足。"
                    print(f"   ⚠️ {msg}")
                    append_error_note(gc, dest_sh.id, "預測紀錄", msg)
                    continue
                    
                if first_run_pca is None: first_run_pca = df_pca_features
                
                sorted_model_names = sorted(result.keys(), key=lambda m: result[m]['Ranks'].get('Overall', 99))
                rows_to_add = []
                for m in sorted_model_names:
                    res = result[m]
                    def get_val(d, k, default="N/A", is_round=True):
                        val = d.get(k)
                        if val is None or pd.isna(val) or val in [np.inf, -np.inf]: return default
                        return round(float(val), 2) if is_round else val
                    
                    rows_to_add.append({
                        "Date": today_str, "Model_Name": m,
                        "Overall_Rank": get_val(res['Ranks'], 'Overall', is_round=False), "Overall_RMSE": get_val(res['RMSE'], 'Overall'),
                        "3D_Rank": get_val(res['Ranks'], '3day', is_round=False), "3D_RMSE": get_val(res['RMSE'], '3day'), "3_Days_Pred(%)": get_val(res['Preds'], '3day'),
                        "7D_Rank": get_val(res['Ranks'], '7day', is_round=False), "7D_RMSE": get_val(res['RMSE'], '7day'), "7_Days_Pred(%)": get_val(res['Preds'], '7day'),
                        "1M_Rank": get_val(res['Ranks'], '1month', is_round=False), "1M_RMSE": get_val(res['RMSE'], '1month'), "1_Month_Pred(%)": get_val(res['Preds'], '1month'),
                        "1Y_Rank": get_val(res['Ranks'], '1year', is_round=False), "1Y_RMSE": get_val(res['RMSE'], '1year'), "1_Year_Pred(%)": get_val(res['Preds'], '1year'),
                        "Status": "Success", "Update_Time": datetime.now().strftime("%H:%M:%S")
                    })
                
                df_rows = pd.DataFrame(rows_to_add)
                
                is_success = safe_gspread_write(gc, dest_sh.id, "預測紀錄", df_rows, mode="clear_update")
                if not is_success:
                    print(f"   ❌ 寫入失敗，請查看上方詳細報錯！")
                    
            except Exception as e:
                msg = f"{today_dot}更新失敗：模型發生錯誤 ({str(e)})。"
                print(f"   ⚠️ 發生崩潰: {msg}")
                traceback.print_exc()
                append_error_note(gc, dest_sh.id, "預測紀錄", msg)

        if first_run_pca is not None:
            print("\n💾 正在備份全域 PCA 特徵矩陣...")
            df_pca_output = first_run_pca.reset_index()
            df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
            safe_gspread_write(gc, lake_sh_id, "global_pca_features", df_pca_output, mode="clear_update")
            
        print("\n✅ 所有獨立檔案更新流程完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生重大錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
