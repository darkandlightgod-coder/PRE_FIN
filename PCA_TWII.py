# -*- coding: utf-8 -*-
"""
V13.7 PCA_TWII.py (終極三維特徵融合 + API避震版)
- 架構大升級：不再只讀取總經資料。現在會自動尋找並融合「總經」、「期貨(TAIFEX)」、「AI輿情(News)」三大特徵池。
- API 避震：加入 find_spreadsheet 自動重試機制，防止 Google API 503/429 暫時性斷線導致崩潰。
- 寫入優化：每日成功預測時將「清空舊資料並貼上新預測」。
- 錯誤處理：若當日資料為空或拋錯，保留舊資料，在最下方附加更新失敗備註。
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
            sh = gc.open_by_key(sp_id)
            try:
                worksheet = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=tab_name, rows=str(len(df)+50), cols=str(len(df.columns)+5))
            
            df = df.fillna("")
            new_headers = df.columns.values.tolist()
            
            if mode == "clear_update":
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
            return True
        except gspread.exceptions.APIError as e:
            print(f"   ⚠️ 寫入時遇到 Google 伺服器忙線 (API Error)，等待 3 秒後重試... ({attempt+1}/3)")
            time.sleep(3)
        except Exception:
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
        except Exception:
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
    df = df.replace("", np.nan).apply(pd.to_numeric, errors='coerce').ffill() 
    df.dropna(axis=1, how='all', inplace=True)
    df.sort_index(inplace=True)
    return df

# 🌟 V13.7 新增：帶有「重試避震機制」的尋找檔案功能，專治 Google 503 錯誤
def find_spreadsheet(gc, file_name, file_url=""):
    for attempt in range(3):
        try:
            if file_url.strip():
                try: 
                    return gc.open_by_url(file_url.strip())
                except Exception: 
                    pass
            
            # 使用更直接的方法呼叫 Google API，降低過度搜尋造成的負載
            return gc.open(file_name)
            
        except gspread.exceptions.SpreadsheetNotFound:
            # 如果是真的找不到檔案，直接回傳 None，不需要重試
            return None
        except gspread.exceptions.APIError as e:
            # 遇到 503 等 API 忙線錯誤，進行重試
            if attempt < 2:
                print(f"   ⚠️ Google API 伺服器忙線中 (錯誤碼: {e.response.status_code})，等待 5 秒後自動重試... ({attempt+1}/3)")
                time.sleep(5)
            else:
                print(f"   ❌ 重試 3 次皆失敗，請稍後再試。")
                raise e
        except Exception as e:
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
    s_y.name = "Target_Close"
    aligned_data = pd.concat([df_X, s_y], axis=1, join='inner').dropna()
    
    if len(aligned_data) < 100: 
        return None, None
    
    y_raw = aligned_data["Target_Close"]
    df_aligned_X = aligned_data.drop(columns=["Target_Close"])
    
    scaler = StandardScaler()
    X_scaled_np = scaler.fit_transform(df_aligned_X)
    df_X_scaled = pd.DataFrame(X_scaled_np, index=df_aligned_X.index, columns=df_aligned_X.columns)
    
    pca = PCA(n_components=min(10, len(df_aligned_X.columns))) 
    X_pca_np = pca.fit_transform(X_scaled_np)
    df_X_pca = pd.DataFrame(X_pca_np, index=df_aligned_X.index, columns=[f"PC{i+1}" for i in range(pca.n_components_)])
    
    merged_for_shift = pd.concat([df_X_scaled, df_X_pca, y_raw], axis=1)

    model_names = ['PCA_Poly_Ridge', 'RandomForest', 'XGBoost']
    model_preds = {m: {} for m in model_names}
    model_rmse = {m: {} for m in model_names} 
    
    for window_name, shift_days in WINDOWS.items():
        y_target = merged_for_shift["Target_Close"].pct_change(shift_days).shift(-shift_days) * 100
        valid_idx = ~y_target.isna()
        
        if valid_idx.sum() < 60:
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
        
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_train_pca_poly = poly.fit_transform(X_pca_v[:split_idx])
        X_test_pca_poly = poly.transform(X_pca_v[split_idx:])
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train_pca_poly, Y_v[:split_idx])
        r_preds_test = ridge.predict(X_test_pca_poly)
        model_rmse['PCA_Poly_Ridge'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], r_preds_test)))
        model_preds['PCA_Poly_Ridge'][window_name] = round(float(ridge.predict(poly.transform(X_latest_pca))[0]), 2)
        
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        rf_preds_test = rf.predict(X_raw_v[split_idx:])
        model_rmse['RandomForest'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], rf_preds_test)))
        model_preds['RandomForest'][window_name] = round(float(rf.predict(X_latest_raw)[0]), 2)
        
        xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, random_state=42, objective='reg:squarederror')
        xgb.fit(X_raw_v[:split_idx], Y_v[:split_idx])
        xgb_preds_test = xgb.predict(X_raw_v[split_idx:])
        model_rmse['XGBoost'][window_name] = float(np.sqrt(mean_squared_error(Y_v[split_idx:], xgb_preds_test)))
        model_preds['XGBoost'][window_name] = round(float(xgb.predict(X_latest_raw)[0]), 2)

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
    print("🏆 PCA x 機器學習 (終極三維特徵融合版 V13.7 API避震版)")
    print("="*70)
    
    try:
        gc = get_gspread_client()
        
        # ==========================================
        # 步驟 1: 匯集所有 Data Lake，組成超級特徵矩陣 df_X_master
        # ==========================================
        print("\n步驟 1: 尋找並融合三大特徵池 (總經、期貨、AI輿情)...")
        
        # 1. 總經特徵
        df_global = pd.DataFrame()
        sh_global = find_spreadsheet(gc, "global_market_factors")
        if sh_global:
            df_global = load_sheet_as_dataframe(sh_global)
            print(f"   ✅ [總經] 載入成功，特徵數: {len(df_global.columns)}")
        else:
            raise ValueError("找不到核心檔案 'global_market_factors'！")

        # 2. 期貨特徵 (TAIFEX)
        df_taifex = pd.DataFrame()
        sh_taifex = find_spreadsheet(gc, "taifex_derivatives_history")
        if sh_taifex:
            df_taifex = load_sheet_as_dataframe(sh_taifex)
            print(f"   ✅ [期貨] 載入成功，特徵數: {len(df_taifex.columns)}")
        else:
            print("   ⚠️ 找不到 'taifex_derivatives_history'，將略過此特徵。")

        # 3. AI 輿情特徵
        df_ai = pd.DataFrame()
        sh_ai = find_spreadsheet(gc, "stock_history_AI_SCORE")
        if sh_ai:
            df_ai = load_sheet_as_dataframe(sh_ai)
            print(f"   ✅ [輿情] 載入成功，特徵數: {len(df_ai.columns)}")
        else:
            print("   ⚠️ 找不到 'stock_history_AI_SCORE'，將略過此特徵。")

        # --- 融合矩陣 ---
        print("   🔄 正在將三大特徵池進行外部合併 (Outer Join)...")
        df_X_master = df_global.copy()
        
        if not df_taifex.empty:
            cols_to_use = df_taifex.columns.difference(df_X_master.columns)
            df_X_master = df_X_master.join(df_taifex[cols_to_use], how='outer')
            
        if not df_ai.empty:
            cols_to_use = df_ai.columns.difference(df_X_master.columns)
            df_X_master = df_X_master.join(df_ai[cols_to_use], how='outer')

        df_X_master = df_X_master.sort_index().ffill().fillna(0)
        print(f"   🔥 終極特徵矩陣融合完畢！總特徵數: {len(df_X_master.columns)}, 總天數: {len(df_X_master)}")


        # ==========================================
        # 步驟 2: 讀取目標股 Y
        # ==========================================
        print("\n步驟 2: 尋找並載入個股歷史資料 (stock_history_13_targets)...")
        stock_sh = find_spreadsheet(gc, "stock_history_13_targets")
        if not stock_sh:
            print("   ⚠️ 找不到 'stock_history_13_targets'！請確認檔案名稱。")
            raise ValueError("找不到個股目標檔案")
        df_stocks = load_sheet_as_dataframe(stock_sh)
        print(f"   ✅ 成功載入！目標股欄位數: {len(df_stocks.columns)}")


        # ==========================================
        # 步驟 3: 循環標的並進行預測
        # ==========================================
        print(f"\n🎯 步驟 3: 啟動特徵對齊與模型預測...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dot = datetime.now().strftime("%Y.%m.%d")
        first_run_pca = None
        lake_sh_id = sh_global.id 
        
        for file_name, file_url in TARGET_SPREADSHEETS.items():
            print(f"\n👉 處理標的: {file_name}")
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
                    
                print(f"   🔍 對齊準備: X(三大特徵融合) + Y(目標: {target_col})")
                
                result, df_pca_features = predict_with_layered_arena(df_X, s_y)
                
                if not result:
                    msg = f"{today_dot}更新失敗：資料對齊後天數不足無法預測。"
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
                        if val is None: return default
                        return round(val, 2) if is_round else val
                    
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
                
                if safe_gspread_write(gc, dest_sh.id, "預測紀錄", df_rows, mode="clear_update"):
                    print(f"   ✅ 成功對齊並【覆寫】最新預測結果。")
                    
            except Exception as e:
                msg = f"{today_dot}更新失敗：模型發生非預期錯誤 ({str(e)})。"
                print(f"   ⚠️ {msg}")
                append_error_note(gc, dest_sh.id, "預測紀錄", msg)
                traceback.print_exc()

        if first_run_pca is not None:
            df_pca_output = first_run_pca.reset_index()
            df_pca_output['Date'] = df_pca_output['Date'].dt.strftime('%Y-%m-%d')
            safe_gspread_write(gc, lake_sh_id, "global_pca_features", df_pca_output, mode="clear_update")
            
        print("\n✅ 所有獨立檔案更新完畢！")
        
    except Exception as e:
        print(f"\n❌ 執行發生錯誤:\n⚠️ {str(e)}\n")
        traceback.print_exc()

if __name__ == "__main__":
    main()
