from flask import Flask, render_template, redirect, url_for, Response, request
import yfinance as yf
import pandas as pd
import os
import time
from datetime import datetime
import numpy as np
import io
import logging
import twstock

# ================= Logging Setup =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Helper Logic =================
WATCHLIST_FILE = "src/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "src/market_scan_list.txt"
GENE_CACHE_FILE = "src/基因快取.csv"

# Secure and multi-layered stock name fetching
def get_stock_name(ticker):
    # Layer 1: Try twstock for the most accurate Chinese name
    try:
        stock_code = ticker.split('.')[0]
        stock = twstock.codes.get(stock_code)
        if stock:
            return stock.name
        # If not found in twstock, fall through to the next layer
    except Exception as e:
        logging.warning(f"twstock lookup failed for {ticker}: {e}. Falling back to yfinance.")

    # Layer 2: Fallback to yfinance if twstock fails or doesn't have the ticker
    try:
        info = yf.Ticker(ticker).info
        return info.get('longName', info.get('shortName', ticker))
    except Exception as e:
        logging.error(f"yfinance fallback also failed for {ticker}: {e}. Returning original ticker as last resort.")
    
    # Layer 3: Absolute failsafe
    return ticker

def get_sector_label(t):
    c = t.split('.')[0]
    if c in ['3481', '2409']: return "[面板]"
    if c in ['3260', '2408', '8299']: return "[記憶體]"
    if c in ['1513', '1519', '1503']: return "[重電]"
    if c in ['2330', '2454', '3017', '2317']: return "[AI核心]"
    return "[熱門]"

def analyze_ticker(ticker, mode, cache_df=None):
    df = yf.download(ticker, period="60d" if mode != 'WEEKLY' else "5y", progress=False, auto_adjust=True, timeout=10)
    if df.empty: return None, None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

    last = df.iloc[-1]
    last_p = float(last['Close'])

    best_p, fit_val = 20, "N/A"
    new_cache_entry = None

    if mode == 'WEEKLY':
        battle = []
        for p in [10, 20, 60]:
            df_strat = df[['Close']].copy()
            df_strat['ma'] = df_strat['Close'].rolling(p).mean().dropna()
            df_strat['above_ma'] = (df_strat['Close'] > df_strat['ma']).astype(int)
            df_strat['signal_change'] = df_strat['above_ma'].diff()
            df_strat['buy_price'] = np.where(df_strat['signal_change'] == 1, df_strat['Close'], np.nan)
            df_strat['entry_price_held'] = df_strat['buy_price'].ffill()
            trade_profits_pct = ((df_strat[df_strat['signal_change'] == -1]['Close'] - df_strat[df_strat['signal_change'] == -1]['entry_price_held']) / df_strat[df_strat['signal_change'] == -1]['entry_price_held'] - 0.004).tolist()
            if df_strat['above_ma'].iloc[-1] == 1:
                last_buy_idx = df_strat[df_strat['signal_change'] == 1].index
                if not last_buy_idx.empty:
                    last_buy_date = last_buy_idx[-1]
                    last_sell_date = df_strat[df_strat['signal_change'] == -1].index
                    last_sell_date = last_sell_date[-1] if not last_sell_date.empty else pd.Timestamp.min # No timezone info needed
                    if last_buy_date > last_sell_date:
                        entry_price_open = df_strat.loc[last_buy_date, 'Close']
                        exit_price_open = df_strat['Close'].iloc[-1]
                        if entry_price_open != 0: trade_profits_pct.append((exit_price_open - entry_price_open) / entry_price_open - 0.004)
            current_capital = 100.0 * np.prod([1 + p for p in trade_profits_pct])
            battle.append((p, current_capital))
        best_p, f_raw = sorted(battle, key=lambda x: x[1], reverse=True)[0]
        fit_val = f"{f_raw-100:.1f}%"
        new_cache_entry = {'ticker': ticker, 'best_p': best_p, 'fit': fit_val}
    else:
        if cache_df is not None and ticker in cache_df.index:
            best_p = int(cache_df.loc[ticker, 'best_p'])
            fit_val = cache_df.loc[ticker, 'fit']
    
    low_20 = df['Low'].tail(20).min()
    target_1382 = round(low_20 + (last_p - low_20) * 1.382, 2)
    ma_val = df['Close'].rolling(best_p).mean().iloc[-1]
    status = "✅強勢" if last_p > ma_val else "❌弱勢"
    is_red = last_p > last['Open']
    signal = "🟢🟢 埋伏" if (is_red and last['Volume'] > df['Volume'].iloc[-2] and status == "✅強勢") else "⚪ 觀察"
    stock_name = get_stock_name(ticker)
    display_name = f"{get_sector_label(ticker)}{stock_name}({ticker.split('.')[0]})"
    result = {"name": display_name, "p": f"{best_p}d", "fit": fit_val, "price": f"{last_p:.1f}", "target": target_1382, "status": status, "signal": signal, "sector": get_sector_label(ticker)}
    return result, new_cache_entry

# Fallback: Simple time string
def get_taipei_time_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def update_cache_file(new_cache, cache_df):
    if not new_cache: return
    new_df = pd.DataFrame(new_cache).set_index('ticker')
    cache_df.update(new_df)
    new_tickers_df = new_df[~new_df.index.isin(cache_df.index)]
    updated_cache_df = pd.concat([cache_df, new_tickers_df])
    updated_cache_df.to_csv(GENE_CACHE_FILE)
    logging.info(f"Gene cache updated with {len(new_cache)} entries.")

def generate_final_table(data):
    buys = [r['sector'] for r in data if r['signal'] == "🟢🟢 埋伏" and r['sector'] != "[熱門]"]
    final_table = []
    for r in data:
        prefix = "🔥🔥【族群起漲!】" if buys.count(r['sector']) >= 2 and r['sector'] != "[熱門]" else ""
        order = f"{prefix}🎯【買入】看 {r['target']}" if r['signal'] == "🟢🟢 埋伏" else "🚀【持有】"
        if r['status'] == "❌弱勢": order = "🔴【避開】趨勢空"
        final_table.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal'], order])
    return final_table

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis_route(mode):
    mode = mode.upper()
    scan_time = get_taipei_time_str()
    list_file = MARKET_SCAN_LIST_FILE if mode.startswith('MARKET') else WATCHLIST_FILE
    with open(list_file, "r", encoding="utf-8") as f: targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    try:
        cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    except FileNotFoundError:
        cache_df = pd.DataFrame(columns=['ticker', 'best_p', 'fit']).set_index('ticker')

    analysis_mode = 'WEEKLY' if mode in ['MARKET_BACKTEST', 'WEEKLY'] else 'DAILY'
    results, new_cache = [], []
    for ticker in targets:
        try:
            result, cache_entry = analyze_ticker(ticker, analysis_mode, cache_df)
            if result:
                if mode == 'MARKET_BACKTEST':
                    try:
                        if float(result['fit'].replace('%','')) > 0: results.append(result)
                    except (ValueError, TypeError): continue
                elif mode == 'MARKET': results.append(result)
                elif mode in ['DAILY', 'WEEKLY']: results.append(result)
            if cache_entry: new_cache.append(cache_entry)
            time.sleep(0.25)
        except Exception as e:
            logging.error(f"Error processing ticker {ticker} in {mode}: {e}")
            continue
    if new_cache: update_cache_file(new_cache, cache_df)
    if mode == 'MARKET_BACKTEST': results.sort(key=lambda r: float(r['fit'].replace('%','')), reverse=True)
    final_table = generate_final_table(results)
    headers = ["標的/族群", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號", "👉 獵人作戰指令"]
    report_info = "每週分析完成，基因快取已更新。" if analysis_mode == 'WEEKLY' else ""
    return render_template('results.html', headers=headers, data=final_table, mode=mode, report_info=report_info, scan_time=scan_time)

@app.route('/watchlist/select')
def select_watchlist_analysis():
    return render_template('watchlist_select.html')

@app.route('/watchlist', methods=['GET', 'POST'])
def manage_watchlist():
    if request.method == 'POST':
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(request.form['watchlist_content'])
        return redirect(url_for('manage_watchlist'))
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f: tickers = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    ticker_details = [{'ticker': t, 'name': get_stock_name(t)} for t in tickers]
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f: content = f.read()
    return render_template('watchlist.html', content=content, ticker_details=ticker_details)

@app.route('/download/<mode>')
def download_report(mode):
    return Response("Download functionality is being updated.", mimetype="text/plain")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
