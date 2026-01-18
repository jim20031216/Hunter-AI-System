# TRIUMPH PROTOCOL - The Final, Correct, and Stable Solution
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
import concurrent.futures

# ================= Bright Data Proxy Setup (TRIUMPH) =================
# The ONLY confirmed working method in Vercel.
# We explicitly pass the proxy to the yf.download function.
PROXY_USERNAME = "brd-customer-hl_a9437f18-zone-residential_proxy1"
PROXY_PASSWORD = "fi5sx9h4kzl6"
PROXY_HOST = "brd.superproxy.io"
PROXY_PORT = 33335
PROXY_URL = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"

# Environment variables are no longer trusted and are removed.
logging.info(">>>>>[TRIUMPH PROTOCOL ENGAGED] All systems unified under yf.download with explicit proxy.<<<<<")

# ================= Logging Setup =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Helper Logic (Vercel Compatible) =================
WATCHLIST_FILE = "/tmp/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "/tmp/market_scan_list.txt"
GENE_CACHE_FILE = "/tmp/基因快取.csv"

# get_stock_name is DECOMMISSIONED. It used yf.Ticker, which is unreliable in Vercel.
# We will use the ticker symbol directly for display.

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

# ================= 2. Core Engine (TRIUMPH PROTOCOL) =================
# This is the completely refactored, stable, and correct core engine.
def run_stable_hunter(mode='DAILY'):
    init_system_files()
    scan_time = get_taipei_time_str()
    analysis_mode = 'WEEKLY' if mode in ['MARKET_BACKTEST', 'WEEKLY'] else 'DAILY'
    is_market_scan = mode.startswith('MARKET') or mode == 'QUICK_SCAN'

    if mode == 'QUICK_SCAN':
        list_file = MARKET_SCAN_LIST_FILE
    else:
        list_file = MARKET_SCAN_LIST_FILE if is_market_scan else WATCHLIST_FILE

    if not os.path.exists(list_file):
        with open(list_file, "w", encoding="utf-8") as f: f.write("# 請在此輸入您的自選股\n")

    with open(list_file, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    
    # CRITICAL: Remove ^TWII for stability if it's not the only target
    if len(targets) > 1 and "^TWII" in targets:
        targets.remove("^TWII")
        logging.info("Removed ^TWII from multi-stock scan for stability.")
        
    if not targets:
        logging.warning("No targets found for analysis. Returning empty results.")
        return [], scan_time, analysis_mode, list_file

    try:
        cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        cache_df = pd.DataFrame(columns=['ticker', 'best_p', 'fit']).set_index('ticker')

    # Unified Data Download
    period = "5y" if analysis_mode == 'WEEKLY' else ("2d" if mode == 'QUICK_SCAN' else "60d")
    all_data = None
    try:
        logging.info(f"Executing unified download for {len(targets)} targets with period '{period}'...")
        all_data = yf.download(
            tickers=targets,
            period=period,
            auto_adjust=False,
            proxy=PROXY_URL,
            timeout=90, # Increased timeout for potentially large downloads
            group_by='ticker' if len(targets) > 1 else None # Use group_by for multi, standard for single
        )
        if all_data.empty:
            raise ValueError("yf.download returned an empty DataFrame.")
        logging.info("Unified download successful.")
    except Exception as e:
        logging.error(f"FATAL: Unified yf.download failed: {e}", exc_info=True)
        error_results = [{"name": f"分析失敗: {t}", "p": "N/A", "fit": "N/A", "price": "N/A", "target": "N/A", "status": "🔴 錯誤", "signal": "Data Error", "order_error": str(e), "sector": "ERROR"} for t in targets]
        return error_results, scan_time, analysis_mode, list_file

    results = []
    new_cache = []

    # Unified Analysis Loop
    for ticker in targets:
        try:
            # Select the dataframe for the current ticker
            if len(targets) > 1:
                df = all_data[ticker]
            else: # If only one ticker, the structure is flat
                df = all_data

            if df.empty or df.isnull().all().all():
                raise ValueError("DataFrame for this ticker is empty or all NaN.")
            df.dropna(inplace=True)
            if df.empty:
                raise ValueError("DataFrame is empty after dropping NaNs.")

            # QUICK_SCAN logic
            if mode == 'QUICK_SCAN':
                if len(df) < 2: continue
                last_day = df.iloc[-1]
                prev_day = df.iloc[-2]
                is_red = last_day['Close'] > last_day['Open']
                is_volume_up = last_day['Volume'] > (prev_day['Volume'] * 1.2)
                if not (is_red and is_volume_up):
                    continue # Skip to next ticker if it doesn't meet quick scan criteria
            
            # --- Standard Analysis Logic ---
            last = df.iloc[-1]
            last_p = float(last['Close'])
            best_p, fit_val = 20, "N/A"

            if analysis_mode == 'WEEKLY':
                # (The same robust weekly backtest logic as before)
                battle = []
                for p in [10, 20, 60]:
                    df_strat = df[['Close']].copy()
                    df_strat['ma'] = df_strat['Close'].rolling(p).mean()
                    df_strat.dropna(inplace=True)
                    if df_strat.empty: continue
                    df_strat['above_ma'] = (df_strat['Close'] > df_strat['ma']).astype(int)
                    df_strat['signal_change'] = df_strat['above_ma'].diff()
                    df_strat['buy_price'] = np.where(df_strat['signal_change'] == 1, df_strat['Close'], np.nan)
                    df_strat['entry_price_held'] = df_strat['buy_price'].ffill()
                    trades = df_strat[df_strat['signal_change'] == -1]
                    trade_profits_pct = []
                    if not trades.empty and not trades['entry_price_held'].isnull().all():
                         trade_profits_pct = ((trades['Close'] - trades['entry_price_held']) / trades['entry_price_held'] - 0.004).tolist()
                    if not df_strat.empty and df_strat['above_ma'].iloc[-1] == 1:
                        last_buy_idx = df_strat[df_strat['signal_change'] == 1].index
                        if not last_buy_idx.empty:
                            entry_price_open = df_strat.loc[last_buy_idx[-1], 'Close']
                            exit_price_open = df_strat['Close'].iloc[-1]
                            if entry_price_open != 0: trade_profits_pct.append((exit_price_open - entry_price_open) / entry_price_open - 0.004)
                    current_capital = 100.0 * np.prod([1 + prof for prof in trade_profits_pct])
                    battle.append((p, current_capital))
                if not battle: raise ValueError("Could not perform weekly backtest.")
                best_p, f_raw = sorted(battle, key=lambda x: x[1], reverse=True)[0]
                fit_val = f"{f_raw-100:.1f}%"
                new_cache.append({'ticker': ticker, 'best_p': best_p, 'fit': fit_val})
            else: # DAILY
                if ticker in cache_df.index:
                    best_p = int(cache_df.loc[ticker, 'best_p'])
                    fit_val = cache_df.loc[ticker, 'fit']

            low_20 = df['Low'].tail(20).min()
            target_1382 = round(low_20 + (last_p - low_20) * 1.382, 2)
            ma_val = df['Close'].rolling(best_p).mean().iloc[-1]
            status = "✅強勢" if last_p > ma_val else "❌弱勢"
            is_red_signal = last_p > last['Open']
            signal = "🟢🟢 埋伏" if (is_red_signal and len(df['Volume']) > 1 and last['Volume'] > df['Volume'].iloc[-2] and status == "✅強勢") else "⚪ 觀察"
            
            # TRIUMPH: Use ticker directly, no more get_stock_name
            display_name = f"{get_sector_label(ticker)}{ticker}"

            results.append({"name": display_name, "p": f"{best_p}d", "fit": fit_val,
                           "price": f"{last_p:.1f}", "target": target_1382, "status": status,
                           "signal": signal, "sector": get_sector_label(ticker)})

        except Exception as e:
            logging.error(f"ANALYSIS ERROR on {ticker}: {e}", exc_info=False)
            results.append({"name": f"分析失敗: {ticker}", "p": "N/A", "fit": "N/A", "price": "N/A", "target": "N/A", "status": "🔴 錯誤", "signal": "Data Error", "order_error": str(e), "sector": "ERROR"})
            continue
    
    # Unified Cache Update
    if new_cache:
        logging.info(f"Updating gene cache with {len(new_cache)} new entries.")
        new_df = pd.DataFrame(new_cache).set_index('ticker')
        updated_cache_df = pd.concat([cache_df[~cache_df.index.isin(new_df.index)], new_df])
        updated_cache_df.to_csv(GENE_CACHE_FILE)
        
    return results, scan_time, analysis_mode, list_file

# ================= 3. Flask Web Routes (TRIUMPH PROTOCOL) =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis(mode):
    # TRIUMPH: Define titles here for clarity
    mode_upper = mode.upper()
    titles = {
        'QUICK_SCAN': '⚡ 市場趨勢快速掃描結果',
        'MARKET': '📡 市場即時掃描結果 (強勢股)',
        'MARKET_BACKTEST': '🧠 全市場潛力股策略回測',
        'DAILY': '🔥 自選股每日追蹤',
        'WEEKLY': '🏥 自選股策略回測'
    }
    title = titles.get(mode_upper, '📊 分析結果')

    # For QUICK_SCAN, we now run the main engine with a specific mode
    data, scan_time, analysis_mode, list_file = run_stable_hunter(mode=mode_upper)
    error_flag = any("ERROR" in r.get("sector", "") for r in data)
    
    if mode_upper == 'MARKET_BACKTEST' and not error_flag:
        data.sort(key=lambda r: float(r['fit'].replace('%', '')) if r.get('fit') and r['fit'] != 'N/A' else -9999, reverse=True)

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
        report_info = f"掃描完成，發現 {len(data)} 個符合「紅K帶量」的潛力目標。"
    
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
        content = "# 請在此輸入您的自選股\n2330.TW\n" # Default content
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(content)

    tickers = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    # TRIUMPH: Removed get_stock_name. Just show the ticker.
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
        csv_data = []
        for r in results:
            csv_data.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal']])

    df = pd.DataFrame(csv_data, columns=headers)
    
    output = io.BytesIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={mode.lower()}_scan_{timestamp}.csv"}
    )

# ================= Main Entry Point for Local Server =================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)
