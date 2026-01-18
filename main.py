# Final Production Code with Multi-Threading Engine and Browser Disguise
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
import requests

# ================= Logging Setup =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Helper Logic =================
WATCHLIST_FILE = "src/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "src/market_scan_list.txt"
GENE_CACHE_FILE = "src/基因快取.csv"

def get_stock_name(ticker):
    # This function can also benefit from the session disguise
    try:
        session = requests.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        info = yf.Ticker(ticker, session=session).info
        name = info.get('longName', info.get('shortName', ticker))
        return name if name and isinstance(name, str) else ticker
    except Exception as e:
        logging.error(f"yfinance name lookup failed for {ticker}: {e}. Returning original ticker.")
        return ticker

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
    if not os.path.exists("src/"):
        os.makedirs("src/")
    if not os.path.exists(MARKET_SCAN_LIST_FILE):
        default_list = ["^TWII", "3481.TW", "2409.TW", "3260.TWO", "2408.TW", "1513.TW", "1519.TW", "2330.TW", "2317.TW", "3017.TW", "2454.TW"]
        with open(MARKET_SCAN_LIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(default_list))
    if not os.path.exists(GENE_CACHE_FILE):
        pd.DataFrame(columns=['ticker', 'best_p', 'fit']).to_csv(GENE_CACHE_FILE, index=False)

# ================= 2. FINAL Core Engine (Multi-Threaded with Browser Disguise) =================
def run_stable_hunter(mode='DAILY'):
    init_system_files()
    scan_time = get_taipei_time_str()
    analysis_mode = 'WEEKLY' if mode in ['MARKET_BACKTEST', 'WEEKLY'] else 'DAILY'

    is_market_scan = mode.startswith('MARKET')
    list_file = MARKET_SCAN_LIST_FILE if is_market_scan else WATCHLIST_FILE
    
    if not is_market_scan and not os.path.exists(WATCHLIST_FILE):
         with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write("# 請在此輸入您的自選股")

    with open(list_file, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        if not targets: return [], scan_time, analysis_mode

    try:
        cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        cache_df = pd.DataFrame(columns=['ticker', 'best_p', 'fit']).set_index('ticker')

    period = "5y" if analysis_mode == 'WEEKLY' else "60d"
    
    results_agg = []
    
    def fetch_and_analyze_ticker(ticker):
        try:
            logging.info(f"THREAD: Fetching data for {ticker} with browser disguise")
            
            session = requests.Session()
            session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

            ticker_obj = yf.Ticker(ticker, session=session)
            df = ticker_obj.history(period=period, auto_adjust=False, timeout=20)
            
            if df.empty:
                raise ValueError("Downloaded DataFrame is empty.")
            df.dropna(inplace=True)
            if df.empty:
                raise ValueError("DataFrame is empty after dropping NaNs.")

            # --- Analysis Logic ---
            last = df.iloc[-1]
            last_p = float(last['Close'])
            best_p, fit_val = 20, "N/A"
            new_cache_item = None

            if analysis_mode == 'WEEKLY':
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
                    if trades.empty or trades['entry_price_held'].isnull().all():
                         trade_profits_pct = []
                    else:
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
                new_cache_item = {'ticker': ticker, 'best_p': best_p, 'fit': fit_val}
            else: # DAILY
                if ticker in cache_df.index:
                    best_p = int(cache_df.loc[ticker, 'best_p'])
                    fit_val = cache_df.loc[ticker, 'fit']

            low_20 = df['Low'].tail(20).min()
            target_1382 = round(low_20 + (last_p - low_20) * 1.382, 2)
            ma_val = df['Close'].rolling(best_p).mean().iloc[-1]
            status = "✅強勢" if last_p > ma_val else "❌弱勢"
            is_red = last_p > last['Open']
            signal = "🟢🟢 埋伏" if (is_red and len(df['Volume']) > 1 and last['Volume'] > df['Volume'].iloc[-2] and status == "✅強勢") else "⚪ 觀察"
            stock_name = get_stock_name(ticker)
            display_name = f"{get_sector_label(ticker)}{stock_name}({ticker.split('.')[0]})"
            
            return {"status": "success", "data": {"name": display_name, "p": f"{best_p}d", "fit": fit_val,
                           "price": f"{last_p:.1f}", "target": target_1382, "status": status,
                           "signal": signal, "sector": get_sector_label(ticker)}, "cache": new_cache_item}
        
        except Exception as e:
            logging.error(f"THREAD ERROR on {ticker}: {e}", exc_info=False)
            return {"status": "error", "data": {"name": f"分析失敗: {ticker}", "p": "N/A", "fit": "N/A", "price": "N/A", "target": "N/A", "status": "🔴 錯誤", "signal": "Data Error", "order_error": str(e), "sector": "ERROR"}, "cache": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(fetch_and_analyze_ticker, ticker): ticker for ticker in targets}
        for future in concurrent.futures.as_completed(future_to_ticker):
            results_agg.append(future.result())

    results, new_cache = [], []
    for res in results_agg:
        results.append(res['data'])
        if res['cache']:
            new_cache.append(res['cache'])
    
    if new_cache:
        logging.info(f"Updating gene cache with {len(new_cache)} new entries.")
        new_df = pd.DataFrame(new_cache).set_index('ticker')
        updated_cache_df = pd.concat([cache_df, new_df])
        updated_cache_df = updated_cache_df[~updated_cache_df.index.duplicated(keep='last')]
        updated_cache_df.to_csv(GENE_CACHE_FILE)
        
    return results, scan_time, analysis_mode

# ================= 3. Flask Web Routes (Unchanged) =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis(mode):
    data, scan_time, analysis_mode = run_stable_hunter(mode=mode.upper())
    error_flag = any("ERROR" in r.get("sector", "") for r in data)
    
    if mode.upper() == 'MARKET_BACKTEST' and not error_flag:
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
    report_info = "每週分析完成，基因快取已更新。" if analysis_mode == 'WEEKLY' else ""
    if error_flag:
        report_info = f"偵測到 {sum(1 for r in data if r.get('sector') == 'ERROR')} 個分析錯誤。系統正在從錯誤中學習。 " + report_info

    return render_template('results.html', headers=headers, data=final_table, mode=mode.upper(), report_info=report_info, scan_time=scan_time, error_flag=error_flag)


@app.route('/watchlist/select')
def select_watchlist_analysis():
    return render_template('watchlist_select.html')

@app.route('/watchlist', methods=['GET', 'POST'])
def manage_watchlist():
    init_system_files()
    if not os.path.exists(WATCHLIST_FILE):
         with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write("# 請在此輸入您的自選股")

    if request.method == 'POST':
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(request.form['watchlist_content'])
        return redirect(url_for('manage_watchlist'))
    
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f: content = f.read()
    
    tickers = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    ticker_details = [{'ticker': t, 'name': get_stock_name(t)} for t in tickers]
    
    return render_template('watchlist.html', content=content, ticker_details=ticker_details)

@app.route('/download/<mode>')
def download_csv(mode):
    results, _, _ = run_stable_hunter(mode=mode.upper())
    
    if any("ERROR" in r.get("sector", "") for r in results):
        headers = ["分析狀態", "詳細錯誤"]
        csv_data = [[r['name'], r.get('order_error', 'N/A')] for r in results]
    else:
        headers = ["標的", "名稱", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號"]
        csv_data = []
        for r in results:
            try:
                parts = r['name'].split('(')
                name_part = parts[0]
                ticker_part = parts[1].replace(')', '')
            except:
                name_part = r['name']
                ticker_part = 'N/A'
            csv_data.append([ticker_part, name_part, r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal']])

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
