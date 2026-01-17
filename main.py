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
import pytz

# ================= Logging Setup =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Helper Logic =================
WATCHLIST_FILE = "src/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "src/market_scan_list.txt"
GENE_CACHE_FILE = "src/基因快取.csv"

# Secure and multi-layered stock name fetching (Retained from previous robust version)
def get_stock_name(ticker):
    try:
        stock_code = ticker.split('.')[0]
        stock = twstock.codes.get(stock_code)
        if stock:
            return stock.name
    except Exception as e:
        logging.warning(f"twstock lookup failed for {ticker}: {e}. Falling back to yfinance.")
    try:
        info = yf.Ticker(ticker).info
        return info.get('longName', info.get('shortName', ticker))
    except Exception as e:
        logging.error(f"yfinance fallback also failed for {ticker}: {e}. Returning original ticker.")
    return ticker

# Secure Taipei time fetching with fallback (Retained from previous robust version)
def get_taipei_time_str():
    try:
        taipei_tz = pytz.timezone('Asia/Taipei')
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_taipei = now_utc.astimezone(taipei_tz)
        return now_taipei.strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception as e:
        logging.warning(f"pytz lookup for Taipei time failed: {e}. Falling back to server time.")
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S (Local)')

# get_sector_label from your V.FINAL.ULTRA
def get_sector_label(t):
    c = t.split('.')[0]
    if c in ['3481', '2409']: return "[面板]"
    if c in ['3260', '2408', '8299']: return "[記憶體]"
    if c in ['1513', '1519', '1503']: return "[重電]"
    if c in ['2330', '2454', '3017', '2317']: return "[AI核心]"
    return "[熱門]"

# init_system logic from your V.FINAL.ULTRA
def init_system_files():
    # Use the market scan list as the default for initialization
    if not os.path.exists(MARKET_SCAN_LIST_FILE):
        default_list = ["^TWII", "3481.TW", "2409.TW", "3260.TWO", "2408.TW", "1513.TW", "1519.TW", "2330.TW", "2317.TW", "3017.TW", "2454.TW"]
        with open(MARKET_SCAN_LIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(default_list))
    if not os.path.exists(GENE_CACHE_FILE):
        pd.DataFrame(columns=['ticker', 'best_p', 'fit']).to_csv(GENE_CACHE_FILE, index=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis_route(mode):
    # This is the new core, directly implementing your V.FINAL.ULTRA logic
    init_system_files()
    mode = mode.upper()
    scan_time = get_taipei_time_str()

    # Determine which list to use
    is_market_scan = mode.startswith('MARKET')
    list_file = MARKET_SCAN_LIST_FILE if is_market_scan else WATCHLIST_FILE
    
    # Ensure watchlist exists if it's selected
    if not is_market_scan and not os.path.exists(WATCHLIST_FILE):
         with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
             f.write("# 請在此輸入您的自選股，一行一檔，例如：\n# 2330.TW\n# 0050.TW")

    with open(list_file, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    results, new_cache = [], []
    try:
        cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        cache_df = pd.DataFrame(columns=['ticker', 'best_p', 'fit']).set_index('ticker')

    analysis_mode = 'WEEKLY' if mode in ['MARKET_BACKTEST', 'WEEKLY'] else 'DAILY'

    for ticker in targets:
        try:
            df = yf.download(ticker, period="60d" if analysis_mode == 'DAILY' else "5y", progress=False, auto_adjust=True, timeout=10)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

            last = df.iloc[-1]
            last_p = float(last['Close'])

            best_p, fit_val = 20, "N/A"
            if analysis_mode == 'WEEKLY':
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
                            last_sell_date_series = df_strat[df_strat['signal_change'] == -1].index
                            last_sell_date = last_sell_date_series[-1] if not last_sell_date_series.empty else pd.Timestamp.min
                            if last_buy_date > last_sell_date:
                                entry_price_open = df_strat.loc[last_buy_date, 'Close']
                                exit_price_open = df_strat['Close'].iloc[-1]
                                if entry_price_open != 0: trade_profits_pct.append((exit_price_open - entry_price_open) / entry_price_open - 0.004)
                    current_capital = 100.0 * np.prod([1 + prof for prof in trade_profits_pct])
                    battle.append((p, current_capital))
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
            is_red = last_p > last['Open']
            signal = "🟢🟢 埋伏" if (is_red and len(df['Volume']) > 1 and last['Volume'] > df['Volume'].iloc[-2] and status == "✅強勢") else "⚪ 觀察"
            
            stock_name = get_stock_name(ticker)
            display_name = f"{get_sector_label(ticker)}{stock_name}({ticker.split('.')[0]})"
            
            result = {"name": display_name, "p": f"{best_p}d", "fit": fit_val,
                      "price": f"{last_p:.1f}", "target": target_1382, "status": status,
                      "signal": signal, "sector": get_sector_label(ticker)}
            
            # This is the critical filter you pointed out was missing
            if mode == 'MARKET':
                if result['status'] == "✅強勢":
                    results.append(result)
            elif mode == 'MARKET_BACKTEST':
                try:
                    if float(result['fit'].replace('%','')) > 0:
                        results.append(result)
                except (ValueError, TypeError):
                    continue
            else: # DAILY, WEEKLY (for watchlist)
                results.append(result)
            
            time.sleep(0.25)
        except Exception as e:
            logging.error(f"Error processing ticker {ticker} in {mode}: {e}")
            continue
    
    # Update cache if weekly analysis was run
    if new_cache:
        new_df = pd.DataFrame(new_cache).set_index('ticker')
        # Combine old and new, preferring new
        # Use concat and drop duplicates, keeping the last one
        combined_df = pd.concat([cache_df, new_df])
        updated_cache_df = combined_df[~combined_df.index.duplicated(keep='last')]
        updated_cache_df.to_csv(GENE_CACHE_FILE)
        logging.info(f"Gene cache updated with {len(new_cache)} entries.")

    if mode == 'MARKET_BACKTEST':
        results.sort(key=lambda r: float(r['fit'].replace('%','')), reverse=True)

    # Final table generation, from your V.FINAL.ULTRA
    buys = [r['sector'] for r in results if r['signal'] == "🟢🟢 埋伏" and r['sector'] != "[熱門]"]
    final_table = []
    for r in results:
        prefix = "🔥🔥【族群起漲!】" if buys.count(r['sector']) >= 2 and r['sector'] != "[熱門]" else ""
        order = f"{prefix}🎯【買入】看 {r['target']}" if r['signal'] == "🟢🟢 埋伏" else "🚀【持有】"
        if r['status'] == "❌弱勢": order = "🔴【避開】趨勢空"
        final_table.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal'], order])

    headers = ["標的/族群", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號", "👉 獵人作戰指令"]
    report_info = "每週分析完成，基因快取已更新。" if analysis_mode == 'WEEKLY' else ""

    return render_template('results.html', headers=headers, data=final_table, mode=mode, report_info=report_info, scan_time=scan_time)

@app.route('/watchlist/select')
def select_watchlist_analysis():
    return render_template('watchlist_select.html')

@app.route('/watchlist', methods=['GET', 'POST'])
def manage_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
         with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
             f.write("# 請在此輸入您的自選股，一行一檔，例如：\n# 2330.TW\n# 0050.TW")

    if request.method == 'POST':
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            f.write(request.form['watchlist_content'])
        return redirect(url_for('manage_watchlist'))
    
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tickers = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    ticker_details = [{'ticker': t, 'name': get_stock_name(t)} for t in tickers]
    
    return render_template('watchlist.html', content=content, ticker_details=ticker_details)

@app.route('/download/<mode>')
def download_report(mode):
    # This functionality can be properly implemented next
    return Response("Download functionality is under construction.", mimetype="text/plain")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
