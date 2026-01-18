# PHOENIX PROTOCOL v1.1 - Proxy Enabled & Engine Fixes
from flask import Flask, render_template, redirect, url_for, Response, request
import yfinance as yf
import pandas as pd
import os
import time
from datetime import datetime
import numpy as np
import io
import logging
import pytz

# ================= Logging Setup =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logging.info(">>>>>[PHOENIX PROTOCOL ENGAGED] All data requests will be routed through Bright Data proxy.<<<<<")

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Helper Logic (Vercel Compatible) =================
WATCHLIST_FILE = "/tmp/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "/tmp/market_scan_list.txt"
GENE_CACHE_FILE = "/tmp/基因快取.csv"
PROXY_STRING = "http://brd-customer-hl_a9437f18-zone-residential_proxy1:fi5sx9h4kzl6@brd.superproxy.io:33335"

def get_taipei_time_str():
    try:
        taipei_tz = pytz.timezone('Asia/Taipei')
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_taipei = now_utc.astimezone(taipei_tz)
        return now_taipei.strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception as e:
        logging.warning(f"pytz lookup for Taipei time failed: {e}. Falling back to server time.")
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S (Local)')

def get_sector_label(t):
    c = t.split('.')[0]
    if c in ['3481', '2409']: return "[面板]"
    if c in ['3260', '2408', '8299']: return "[記憶體]"
    if c in ['1513', '1519', '1503']: return "[重電]"
    if c in ['2330', '2454', '3017', '2317']: return "[AI核心]"
    return "[熱門]"

def init_system_files():
    if not os.path.exists(MARKET_SCAN_LIST_FILE):
        default_list = ["^TWII", "3481.TW", "2409.TW", "3260.TWO", "2408.TW", "1513.TW", "1519.TW", "2330.TW", "2317.TW", "3017.TW", "2454.TW"]
        with open(MARKET_SCAN_LIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(default_list))
    if not os.path.exists(GENE_CACHE_FILE):
        pd.DataFrame(columns=['ticker', 'best_p', 'fit']).to_csv(GENE_CACHE_FILE, index=False)

# ================= 2. Core Engine (PHOENIX PROTOCOL v1.1) =================
def run_stable_hunter(mode='DAILY'):
    init_system_files()
    scan_time = get_taipei_time_str()
    analysis_mode = 'WEEKLY' if mode in ['MARKET_BACKTEST', 'WEEKLY'] else 'DAILY'
    is_market_scan = mode.startswith('MARKET') or mode == 'QUICK_SCAN'

    list_file = MARKET_SCAN_LIST_FILE if is_market_scan else WATCHLIST_FILE
    if not os.path.exists(list_file):
        with open(list_file, "w", encoding="utf-8") as f: f.write("# 請在此輸入您的自選股\n")

    with open(list_file, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    
    is_single_target = len(targets) == 1
    if not is_single_target and "^TWII" in targets:
        targets.remove("^TWII")
        is_single_target = len(targets) == 1
        
    if not targets:
        return [], scan_time, analysis_mode, list_file

    try:
        cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        cache_df = pd.DataFrame(columns=['ticker', 'best_p', 'fit']).set_index('ticker')

    period = "5y" if analysis_mode == 'WEEKLY' else ("2d" if mode == 'QUICK_SCAN' else "60d")
    all_data = None
    try:
        logging.info(f"Executing PHOENIX PROTOCOL download via proxy for {len(targets)} targets with period '{period}'...")
        all_data = yf.download(tickers=targets, period=period, auto_adjust=False, proxy=PROXY_STRING, timeout=60, group_by='ticker' if not is_single_target else None)
        if all_data.empty:
            raise ValueError("yf.download returned an empty DataFrame. The proxy may be failing or the ticker is invalid.")
        logging.info("PHOENIX PROTOCOL download successful.")
    except Exception as e:
        logging.error(f"FATAL: PHOENIX PROTOCOL download failed: {e}", exc_info=True)
        error_results = [{"name": f"分析失敗: {t}", "p": "N/A", "fit": "N/A", "price": "N/A", "target": "N/A", "status": "🔴 錯誤", "signal": "Data Error", "order_error": str(e), "sector": "ERROR"} for t in targets]
        return error_results, scan_time, analysis_mode, list_file

    results = []
    new_cache = []

    for ticker in targets:
        try:
            df = all_data if is_single_target else all_data[ticker]
            if df.empty or df.isnull().all().all(): raise ValueError("DataFrame for this ticker is empty.")
            df.dropna(inplace=True)
            if df.empty: raise ValueError("DataFrame is empty after dropping NaNs.")

            if mode == 'QUICK_SCAN':
                if len(df) < 2: continue
                last_day, prev_day = df.iloc[-1], df.iloc[-2]
                if not (last_day['Close'] > last_day['Open'] and last_day['Volume'] > (prev_day['Volume'] * 1.2)): continue
            
            last_p = float(df.iloc[-1]['Close'])
            best_p, fit_val = 20, "N/A"

            if analysis_mode == 'WEEKLY':
                # PHOENIX FIX 1: Check for sufficient data history
                if len(df) < 120: # At least ~6 months of data for a meaningful test
                    fit_val = "數據不足"
                    new_cache.append({'ticker': ticker, 'best_p': best_p, 'fit': fit_val})
                else:
                    battle = []
                    for p in [10, 20, 60]:
                        df_strat = df[['Close']].copy()
                        df_strat['ma'] = df_strat['Close'].rolling(p).mean()
                        if df_strat['ma'].isnull().all(): continue
                        df_strat.dropna(inplace=True)
                        df_strat['above_ma'] = (df_strat['Close'] > df_strat['ma']).astype(int)
                        df_strat['signal_change'] = df_strat['above_ma'].diff()
                        
                        trade_profits_pct = []
                        if 1 in df_strat['signal_change'].values: # Has at least one buy signal
                            df_strat['buy_price'] = np.where(df_strat['signal_change'] == 1, df_strat['Close'], np.nan)
                            df_strat['entry_price_held'] = df_strat['buy_price'].ffill()
                            trades = df_strat[df_strat['signal_change'] == -1]
                            if not trades.empty and not trades['entry_price_held'].isnull().all():
                                 trade_profits_pct.extend(((trades['Close'] - trades['entry_price_held']) / trades['entry_price_held'] - 0.004).tolist())

                        if df_strat['above_ma'].iloc[-1] == 1:
                            last_buy_idx = df_strat[df_strat['signal_change'] == 1].index
                            if not last_buy_idx.empty:
                                entry_price_open = df_strat.loc[last_buy_idx[-1], 'Close']
                                exit_price_open = df_strat['Close'].iloc[-1]
                                if entry_price_open != 0: trade_profits_pct.append((exit_price_open - entry_price_open) / entry_price_open - 0.004)
                        
                        # PHOENIX FIX 2: Handle no-trade scenarios
                        if not trade_profits_pct:
                            battle.append((p, "無交易"))
                        else:
                            current_capital = 100.0 * np.prod([1 + prof for prof in trade_profits_pct])
                            battle.append((p, current_capital))
                    
                    if not battle:
                        best_p, fit_val = 20, "回測失敗"
                    else:
                        # Filter out "無交易" before sorting if possible
                        valid_battles = [b for b in battle if isinstance(b[1], (int, float))]
                        if not valid_battles:
                            best_p, fit_val = 20, "無交易"
                        else:
                            best_p, f_raw = sorted(valid_battles, key=lambda x: x[1], reverse=True)[0]
                            fit_val = f"{f_raw-100:.1f}%"
                    new_cache.append({'ticker': ticker, 'best_p': best_p, 'fit': fit_val})
            else:
                if ticker in cache_df.index:
                    best_p = int(cache_df.loc[ticker, 'best_p'])
                    fit_val = cache_df.loc[ticker, 'fit']

            low_20 = df['Low'].tail(20).min()
            target_1382 = round(low_20 + (last_p - low_20) * 1.382, 2)
            ma_val = df['Close'].rolling(best_p).mean().iloc[-1]
            status = "✅強勢" if last_p > ma_val else "❌弱勢"
            is_red_signal = last_p > df.iloc[-1]['Open']
            is_vol_up = len(df['Volume']) > 1 and df.iloc[-1]['Volume'] > df.iloc[-2]['Volume']
            signal = "🟢🟢 埋伏" if is_red_signal and is_vol_up and status == "✅強勢" else "⚪ 觀察"
            display_name = f"{get_sector_label(ticker)}{ticker}"

            results.append({"name": display_name, "p": f"{best_p}d", "fit": fit_val, "price": f"{last_p:.1f}", "target": target_1382, "status": status, "signal": signal, "sector": get_sector_label(ticker)})

        except Exception as e:
            logging.error(f"ANALYSIS ERROR on {ticker}: {e}", exc_info=False)
            results.append({"name": f"分析失敗: {ticker}", "p": "N/A", "fit": "N/A", "price": "N/A", "target": "N/A", "status": "🔴 錯誤", "signal": "Data Error", "order_error": str(e), "sector": "ERROR"})
            continue
    
    if new_cache:
        logging.info(f"Updating gene cache with {len(new_cache)} new entries.")
        new_df = pd.DataFrame(new_cache).set_index('ticker')
        updated_cache_df = pd.concat([cache_df[~cache_df.index.isin(new_df.index)], new_df])
        updated_cache_df.to_csv(GENE_CACHE_FILE)
        
    return results, scan_time, analysis_mode, list_file

# ================= 3. Flask Web Routes (PHOENIX PROTOCOL v1.1) =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis(mode):
    mode_upper = mode.upper()
    titles = {'QUICK_SCAN': '⚡ 市場趨勢快速掃描結果', 'MARKET': '📡 市場即時掃描結果 (強勢股)', 'MARKET_BACKTEST': '🧠 全市場潛力股策略回測', 'DAILY': '🔥 自選股每日追蹤', 'WEEKLY': '🏥 自選股策略回測'}
    title = titles.get(mode_upper, '📊 分析結果')
    data, scan_time, analysis_mode, list_file = run_stable_hunter(mode=mode_upper)
    error_flag = any("ERROR" in r.get("sector", "") for r in data)
    
    if mode_upper == 'MARKET_BACKTEST' and not error_flag:
        data.sort(key=lambda r: float(r['fit'].replace('%', '')) if isinstance(r.get('fit'), str) and '%' in r['fit'] else -9999, reverse=True)

    buys = [r['sector'] for r in data if r.get('signal') == "🟢🟢 埋伏" and r.get('sector') != "[熱門]" and not "ERROR" in r.get('sector', "")]
    final_table = []
    for r in data:
        if r.get("sector") == "ERROR":
            final_table.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal'], r.get('order_error', 'Unknown Error')])
        else:
            prefix = "🔥🔥【族群起漲!】" if buys.count(r['sector']) >= 2 and r['sector'] != "[熱門]" else ""
            order = f"{prefix}🎯【買入】看 {r['target']}" if r['signal'] == "🟢🟢 埋伏" else "🚀【持有】"
            if r['status'] == "❌弱勢": order = "🔴【避開】趨勢空"
            final_table.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal'], order])

    headers = ["標的/族群", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號", "👉 獵人作戰指令"]
    report_info = ""
    if mode_upper == 'WEEKLY':
        report_info = "每週分析完成，基因快取已更新。"
    elif mode_upper == 'QUICK_SCAN':
        successful_targets = [d for d in data if d.get("sector") != "ERROR"]
        report_info = f"掃描完成，發現 {len(successful_targets)} 個出現「紅K帶量」短期訊號的目標。請結合「狀態」欄位判斷主要趨勢。"
    if error_flag:
        report_info = f"偵測到 {sum(1 for r in data if r.get('sector') == 'ERROR')} 個分析錯誤。 " + report_info

    return render_template('results.html', title=title, headers=headers, data=final_table, mode=mode_upper, report_info=report_info, scan_time=scan_time, error_flag=error_flag, list_file=list_file)

@app.route('/watchlist/select')
def select_watchlist_analysis():
    return render_template('watchlist_select.html')

@app.route('/watchlist', methods=['GET', 'POST'])
def manage_watchlist():
    init_system_files()
    if request.method == 'POST':
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(request.form['watchlist_content'])
        return redirect(url_for('manage_watchlist'))
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f: content = f.read()
    except FileNotFoundError:
        content = "# 請在此輸入您的自選股\n2330.TW\n"
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(content)
    tickers = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    ticker_details = [{'ticker': t, 'name': t} for t in tickers]
    return render_template('watchlist.html', content=content, ticker_details=ticker_details)

@app.route('/download/<mode>')
def download_csv(mode):
    results, _, _, _ = run_stable_hunter(mode=mode.upper())
    if any("ERROR" in r.get("sector", "") for r in results):
        headers = ["分析狀態", "詳細錯誤"]
        csv_data = [[r['name'], r.get('order_error', 'N/A')] for r in results]
    else:
        headers = ["標的", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號"]
        csv_data = [[r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal']] for r in results]
    df = pd.DataFrame(csv_data, columns=headers)
    output = io.BytesIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={mode.lower()}_scan_{timestamp}.csv"})

# ================= Main Entry Point for Local Server =================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)
