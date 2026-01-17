from flask import Flask, render_template, redirect, url_for, Response
import yfinance as yf
import pandas as pd
import os
import time
from datetime import datetime
import numpy as np
import io

# ================= Flask App Initialization =================
app = Flask(__name__)

# ================= 1. Core Files & Sector Logic =================
WATCHLIST_FILE = "src/我的自選清單.txt"
MARKET_SCAN_LIST_FILE = "src/market_scan_list.txt" # New file for market scan
GENE_CACHE_FILE = "src/基因快取.csv"

def get_sector_label(t):
    c = t.split('.')[0]
    if c in ['3481', '2409']: return "[面板]"
    if c in ['3260', '2408', '8299']: return "[記憶體]"
    if c in ['1513', '1519', '1503']: return "[重電]"
    if c in ['2330', '2454', '3017', '2317']: return "[AI核心]"
    return "[熱門]"

# ================= 2. Core Analysis Engine =================
def analyze_ticker(ticker, mode, cache_df=None):
    """
    Analyzes a single ticker. Extracted for reusability.
    """
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
            # (Weekly analysis logic remains the same...)
            df_strat = df[['Close']].copy()
            df_strat['ma'] = df_strat['Close'].rolling(p).mean()
            df_strat = df_strat.dropna()
            df_strat['above_ma'] = (df_strat['Close'] > df_strat['ma']).astype(int)
            df_strat['signal_change'] = df_strat['above_ma'].diff()
            df_strat['buy_price'] = np.where(df_strat['signal_change'] == 1, df_strat['Close'], np.nan)
            df_strat['sell_price'] = np.where(df_strat['signal_change'] == -1, df_strat['Close'], np.nan)
            df_strat['entry_price_held'] = df_strat['buy_price'].ffill()

            trade_profits_pct = []
            sell_days = df_strat[df_strat['signal_change'] == -1]
            for idx, row in sell_days.iterrows():
                entry_price = df_strat.loc[idx, 'entry_price_held']
                exit_price = row['Close']
                if pd.notna(entry_price) and entry_price != 0:
                    profit = (exit_price - entry_price) / entry_price - 0.004
                    trade_profits_pct.append(profit)

            if df_strat['above_ma'].iloc[-1] == 1:
                last_buy_idx = df_strat[df_strat['signal_change'] == 1].index
                if not last_buy_idx.empty:
                    last_buy_date = last_buy_idx[-1]
                    last_sell_date = df_strat[df_strat['signal_change'] == -1].index
                    last_sell_date = last_sell_date[-1] if not last_sell_date.empty else pd.Timestamp.min
                    if last_buy_date > last_sell_date:
                        entry_price_open = df_strat.loc[last_buy_date, 'Close']
                        exit_price_open = df_strat['Close'].iloc[-1]
                        if entry_price_open != 0:
                            profit_open = (exit_price_open - entry_price_open) / entry_price_open - 0.004
                            trade_profits_pct.append(profit_open)
            
            current_capital = 100.0
            for profit_pct in trade_profits_pct:
                current_capital *= (1 + profit_pct)
            battle.append((p, current_capital))
        
        best_p, f_raw = sorted(battle, key=lambda x: x[1], reverse=True)[0]
        fit_val = f"{f_raw-100:.1f}%"
        new_cache_entry = {'ticker': ticker, 'best_p': best_p, 'fit': fit_val}
    else: # DAILY or MARKET mode
        if cache_df is not None and ticker in cache_df.index:
            best_p = int(cache_df.loc[ticker, 'best_p'])
            fit_val = cache_df.loc[ticker, 'fit']
    
    low_20 = df['Low'].tail(20).min()
    target_1382 = round(low_20 + (last_p - low_20) * 1.382, 2)
    ma_val = df['Close'].rolling(best_p).mean().iloc[-1]
    status = "✅強勢" if last_p > ma_val else "❌弱勢"
    is_red = last_p > last['Open']
    signal = "🟢🟢 埋伏" if (is_red and last['Volume'] > df['Volume'].iloc[-2] and status == "✅強勢") else "⚪ 觀察"

    result = {"name": f"{get_sector_label(ticker)}{ticker}", "p": f"{best_p}d", "fit": fit_val,
                    "price": f"{last_p:.1f}", "target": target_1382, "status": status,
                    "signal": signal, "sector": get_sector_label(ticker)}
    
    return result, new_cache_entry

def run_stable_hunter(mode='DAILY'):
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    results, new_cache = [], []
    cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')

    for t in targets:
        try:
            result, cache_entry = analyze_ticker(t, mode, cache_df)
            if result:
                results.append(result)
            if cache_entry:
                new_cache.append(cache_entry)
            time.sleep(0.5)
        except Exception as e:
            print(f"Error processing watchlist ticker {t}: {e}")
            continue

    # Removed writing to GENE_CACHE_FILE for Vercel compatibility
    # if mode == 'WEEKLY': pd.DataFrame(new_cache).to_csv(GENE_CACHE_FILE, index=False)
    return results

def run_market_scan(): # New function for market scanning
    with open(MARKET_SCAN_LIST_FILE, "r", encoding="utf-8") as f:
        targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        
    results = []
    cache_df = pd.read_csv(GENE_CACHE_FILE).set_index('ticker')
    
    for t in targets:
        try:
            # We always use 'DAILY' equivalent logic for market scan
            result, _ = analyze_ticker(t, 'DAILY', cache_df)
            # The key difference: only include strong stocks
            if result and result['status'] == "✅強勢":
                results.append(result)
            time.sleep(0.5) # Keep the delay to be nice to the API
        except Exception as e:
            print(f"Error processing market ticker {t}: {e}")
            continue
            
    scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return results, scan_time

def generate_final_table(data):
    buys = [r['sector'] for r in data if r['signal'] == "🟢🟢 埋伏" and r['sector'] != "[熱門]"]
    final_table = []
    for r in data:
        prefix = "🔥🔥【族群起漲!】" if buys.count(r['sector']) >= 2 else ""
        order = f"{prefix}🎯【買入】看 {r['target']}" if r['signal'] == "🟢🟢 埋伏" else "🚀【持有】"
        if r['status'] == "❌弱勢": order = "🔴【避開】趨勢空"
        final_table.append([r['name'], r['p'], r['fit'], r['price'], r['target'], r['status'], r['signal'], order])
    return final_table

# ================= 3. Web Application Routes =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run/<mode>')
def run_analysis(mode):
    mode = mode.upper()
    scan_time = None # Initialize scan_time

    if mode == 'MARKET':
        data, scan_time = run_market_scan()
    elif mode in ['DAILY', 'WEEKLY']:
        data = run_stable_hunter(mode=mode)
    else:
        return redirect(url_for('index'))

    final_table = generate_final_table(data)

    headers = ["標的/族群", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號", "👉 獵人作戰指令"]
    
    report_info = ""
    if mode == 'WEEKLY':
        report_info = "每週分析無法在雲端版更新基因快取檔案，建議在本機執行。"
    
    return render_template('results.html', headers=headers, data=final_table, mode=mode, report_info=report_info, scan_time=scan_time)

@app.route('/download/<mode>')
def download_report(mode):
    mode = mode.upper()
    
    if mode == 'MARKET':
        data, _ = run_market_scan()
    elif mode in ['DAILY', 'WEEKLY']:
        data = run_stable_hunter(mode=mode)
    else:
        return "Invalid mode", 400

    final_table = generate_final_table(data)
    
    headers = ["標的/族群", "基因", "5年戰績", "現價", "1.382預判", "狀態", "訊號", "👉 獵人作戰指令"]
    df = pd.DataFrame(final_table, columns=headers)
    
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    csv_data = output.getvalue()
    
    timestamp = datetime.now().strftime('%Y%m%d')
    filename = f"analysis_report_{mode.lower()}_{timestamp}.csv"
    
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition":
                 f"attachment; filename={filename}"})


# ================= Main Entry Point for Web Server =================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
