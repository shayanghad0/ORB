import os
import json
import datetime
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64
from io import BytesIO
import webbrowser

# ============================================================
# 1. UTILITY FUNCTIONS
# ============================================================

def list_json_files(directory='.'):
    """Return list of .json files in the given directory."""
    files = [f for f in os.listdir(directory) if f.endswith('.json')]
    return sorted(files)

def load_data(filepath):
    """Load JSON data and convert to list of dicts with datetime objects."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    for bar in data:
        # Parse ISO datetime; assume it's already in NY time (with offset)
        bar['dt'] = datetime.datetime.fromisoformat(bar['time'])
        # We'll keep the offset, but we only need time-of-day
    return data

def time_to_seconds(t):
    """Convert time object to seconds from midnight."""
    return t.hour*3600 + t.minute*60 + t.second

def time_in_range(t, start_str, end_str):
    """Check if time t is within [start_str, end_str) (exclusive end)."""
    start = datetime.time.fromisoformat(start_str)
    end = datetime.time.fromisoformat(end_str)
    # Handle case where end might be 24:00? Not needed.
    return start <= t < end

# ============================================================
# 2. BACKTEST ENGINE
# ============================================================

def backtest_orb(data, range_session, trade_session, tp_pct, sl_pct):
    """
    Run backtest on 1-min OHLCV data.
    Returns:
        trades: list of trade dicts
        equity_curve: list of (datetime, equity)
    """
    # Input sessions: strings like "0930-0936" and "0930-1130"
    range_start, range_end = range_session.split('-')
    trade_start, trade_end = trade_session.split('-')

    # Precompute time ranges (as seconds from midnight for efficiency)
    range_start_sec = time_to_seconds(datetime.time.fromisoformat(range_start))
    range_end_sec = time_to_seconds(datetime.time.fromisoformat(range_end))
    trade_start_sec = time_to_seconds(datetime.time.fromisoformat(trade_start))
    trade_end_sec = time_to_seconds(datetime.time.fromisoformat(trade_end))

    # State variables
    orb_high = None
    orb_low = None
    range_locked = False
    range_building = False
    range_bar_count = 0
    trade_active = False
    trade_long = False
    entry_price = None
    tp_price = None
    sl_price = None
    day_done = False
    trades = []
    equity_curve = []  # list of (timestamp, equity) after each bar
    # We'll compute equity as balance if we start with initial capital = 10000
    initial_capital = 10000.0
    balance = initial_capital
    # We'll track the current trade's PnL if active, but for simplicity we'll just record closed trades.

    # Iterate over bars (index needed)
    for i, bar in enumerate(data):
        dt = bar['dt']
        t_sec = time_to_seconds(dt.time())
        high = bar['high']
        low = bar['low']
        close = bar['close']

        # Determine if we are in range session and trade session
        in_range = (range_start_sec <= t_sec < range_end_sec)
        in_trade = (trade_start_sec <= t_sec < trade_end_sec)

        # Reset at start of new day? Assuming data is one day only, but we handle multi-day.
        # For simplicity, we assume one day. But if multiple days, we need to reset daily.
        # We'll detect if time wraps around (i.e., dt is not same day as previous)
        if i > 0 and dt.date() != data[i-1]['dt'].date():
            # New day: reset all state
            orb_high = None
            orb_low = None
            range_locked = False
            range_building = False
            range_bar_count = 0
            trade_active = False
            trade_long = False
            entry_price = None
            tp_price = None
            sl_price = None
            day_done = False
            # Note: we don't reset balance; we keep cumulative.

        # --- Build range ---
        if in_range and not range_locked:
            if orb_high is None:
                orb_high = high
                orb_low = low
                range_building = True
                range_bar_count = 1
            else:
                orb_high = max(orb_high, high)
                orb_low = min(orb_low, low)
                range_bar_count += 1

        # Lock range when we leave range window
        if not in_range and range_building and not range_locked:
            range_locked = True
            # Range is now fixed

        # --- Signal detection (only if range locked, not day_done, not trade_active, and in_trade) ---
        bullish_bo = False
        bearish_bo = False
        if range_locked and not day_done and not trade_active and in_trade:
            if close > orb_high and (i == 0 or data[i-1]['close'] <= orb_high):
                bullish_bo = True
            elif close < orb_low and (i == 0 or data[i-1]['close'] >= orb_low):
                bearish_bo = True

        # --- Enter long ---
        if bullish_bo:
            trade_active = True
            trade_long = True
            entry_price = close
            tp_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
            # Record entry trade info
            trade = {
                'entry_time': dt.isoformat(),
                'entry_price': entry_price,
                'direction': 'LONG',
                'exit_time': None,
                'exit_price': None,
                'pnl': None,
                'pnl_pct': None,
                'status': 'OPEN'
            }
            trades.append(trade)  # will update later

        # --- Enter short ---
        if bearish_bo:
            trade_active = True
            trade_long = False
            entry_price = close
            tp_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)
            trade = {
                'entry_time': dt.isoformat(),
                'entry_price': entry_price,
                'direction': 'SHORT',
                'exit_time': None,
                'exit_price': None,
                'pnl': None,
                'pnl_pct': None,
                'status': 'OPEN'
            }
            trades.append(trade)

        # --- Manage open trade ---
        if trade_active:
            hit_tp = False
            hit_sl = False
            if trade_long:
                if high >= tp_price:
                    hit_tp = True
                elif low <= sl_price:
                    hit_sl = True
            else:  # short
                if low <= tp_price:
                    hit_tp = True
                elif high >= sl_price:
                    hit_sl = True

            if hit_tp or hit_sl:
                # Close trade at the bar's close? In the Pine script, they check if price hits during the bar.
                # They likely check intra-bar, but we only have OHLC, so we use the bar's high/low.
                # Exit price: for TP, we use the TP price if hit; else SL price.
                exit_price = tp_price if hit_tp else sl_price
                # However, the exact price might be beyond TP/SL, but we'll use the exact target.
                # For PnL, we'll compute with exit_price.
                # Update trade record
                if trades and trades[-1]['status'] == 'OPEN':
                    trade = trades[-1]
                    trade['exit_time'] = dt.isoformat()
                    trade['exit_price'] = exit_price
                    # Compute PnL in points (price difference)
                    if trade_long:
                        pnl = exit_price - entry_price
                    else:
                        pnl = entry_price - exit_price
                    trade['pnl'] = pnl
                    trade['pnl_pct'] = pnl / entry_price * 100
                    trade['status'] = 'CLOSED'
                    balance += pnl  # assuming 1 unit trade
                trade_active = False
                day_done = True

        # Record equity after each bar (if trade active, we mark-to-market)
        if trade_active:
            # Mark-to-market: current equity = balance + unrealized PnL
            if trade_long:
                unrealized = close - entry_price
            else:
                unrealized = entry_price - close
            current_equity = balance + unrealized
        else:
            current_equity = balance
        equity_curve.append((dt, current_equity))

    # After loop, if there is an open trade, we can close at last bar (optional)
    if trade_active and trades and trades[-1]['status'] == 'OPEN':
        # Close at last close
        trade = trades[-1]
        trade['exit_time'] = data[-1]['dt'].isoformat()
        trade['exit_price'] = data[-1]['close']
        if trade_long:
            pnl = data[-1]['close'] - entry_price
        else:
            pnl = entry_price - data[-1]['close']
        trade['pnl'] = pnl
        trade['pnl_pct'] = pnl / entry_price * 100
        trade['status'] = 'CLOSED'
        balance += pnl

    # Return trades and equity curve
    return trades, equity_curve

# ============================================================
# 3. REPORT GENERATION (HTML + CHART)
# ============================================================

def generate_html_report(trades, equity_curve, symbol, date_str, output_html='report.html'):
    """Generate an HTML report with summary stats, trade list, and equity curve chart."""
    # Calculate statistics
    total_trades = len(trades)
    if total_trades == 0:
        win_rate = 0
        avg_pnl = 0
        total_pnl = 0
        max_profit = 0
        max_loss = 0
    else:
        closed_trades = [t for t in trades if t['status'] == 'CLOSED']
        total_closed = len(closed_trades)
        wins = [t for t in closed_trades if t['pnl'] > 0]
        losses = [t for t in closed_trades if t['pnl'] < 0]
        win_rate = len(wins) / total_closed * 100 if total_closed > 0 else 0
        total_pnl = sum(t['pnl'] for t in closed_trades)
        avg_pnl = total_pnl / total_closed if total_closed > 0 else 0
        max_profit = max([t['pnl'] for t in closed_trades]) if closed_trades else 0
        max_loss = min([t['pnl'] for t in closed_trades]) if closed_trades else 0

    # Build HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>ORB Backtest Report - {symbol} {date_str}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #2c3e50; }}
            .summary {{ display: flex; flex-wrap: wrap; gap: 20px; }}
            .stat {{ background: #f8f9fa; padding: 10px 20px; border-radius: 8px; border-left: 4px solid #3498db; }}
            .stat-label {{ font-weight: bold; color: #555; }}
            .stat-value {{ font-size: 1.2em; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
            th {{ background: #2c3e50; color: white; }}
            tr:nth-child(even) {{ background: #f2f2f2; }}
            .profit {{ color: green; }}
            .loss {{ color: red; }}
            img {{ max-width: 100%; height: auto; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <h1>ORB Backtest Report</h1>
        <p><strong>Symbol:</strong> {symbol} &nbsp; <strong>Date:</strong> {date_str}</p>
        <p><strong>Range Session:</strong> 09:30-09:36 &nbsp; <strong>Trading Session:</strong> 09:30-11:30</p>
        <p><strong>TP:</strong> 0.5% &nbsp; <strong>SL:</strong> 0.25%</p>

        <h2>Summary</h2>
        <div class="summary">
            <div class="stat"><span class="stat-label">Total Trades</span><br><span class="stat-value">{total_trades}</span></div>
            <div class="stat"><span class="stat-label">Win Rate</span><br><span class="stat-value">{win_rate:.2f}%</span></div>
            <div class="stat"><span class="stat-label">Total PnL (points)</span><br><span class="stat-value">{total_pnl:.2f}</span></div>
            <div class="stat"><span class="stat-label">Avg PnL per Trade</span><br><span class="stat-value">{avg_pnl:.2f}</span></div>
            <div class="stat"><span class="stat-label">Max Profit</span><br><span class="stat-value">{max_profit:.2f}</span></div>
            <div class="stat"><span class="stat-label">Max Loss</span><br><span class="stat-value">{max_loss:.2f}</span></div>
        </div>

        <h2>Equity Curve</h2>
        <img src="data:image/png;base64,{generate_chart(equity_curve)}" alt="Equity Curve">

        <h2>Trade List</h2>
        <table>
            <thead>
                <tr>
                    <th>Entry Time</th>
                    <th>Direction</th>
                    <th>Entry Price</th>
                    <th>Exit Time</th>
                    <th>Exit Price</th>
                    <th>PnL (points)</th>
                    <th>PnL %</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    """

    for t in trades:
        direction = t['direction']
        entry_time = t['entry_time']
        entry_price = f"{t['entry_price']:.2f}"
        exit_time = t['exit_time'] or '-'
        exit_price = f"{t['exit_price']:.2f}" if t['exit_price'] is not None else '-'
        pnl = t['pnl']
        pnl_str = f"{pnl:.2f}" if pnl is not None else '-'
        pnl_pct_str = f"{t['pnl_pct']:.2f}%" if t['pnl_pct'] is not None else '-'
        status = t['status']
        pnl_class = ''
        if pnl is not None:
            pnl_class = 'profit' if pnl > 0 else 'loss'
        html += f"""
                <tr>
                    <td>{entry_time}</td>
                    <td>{direction}</td>
                    <td>{entry_price}</td>
                    <td>{exit_time}</td>
                    <td>{exit_price}</td>
                    <td class="{pnl_class}">{pnl_str}</td>
                    <td class="{pnl_class}">{pnl_pct_str}</td>
                    <td>{status}</td>
                </tr>
        """

    html += """
            </tbody>
        </table>
    </body>
    </html>
    """

    with open(output_html, 'w') as f:
        f.write(html)
    print(f"Report saved to {output_html}")

def generate_chart(equity_curve):
    """Generate equity curve chart and return base64 encoded PNG."""
    if not equity_curve:
        # Return a blank image or placeholder
        return ''
    dates = [e[0] for e in equity_curve]
    equity = [e[1] for e in equity_curve]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(dates, equity, color='blue', linewidth=2)
    ax.set_xlabel('Time')
    ax.set_ylabel('Equity (points)')
    ax.set_title('Equity Curve')
    ax.grid(True, linestyle='--', alpha=0.7)
    # Format x-axis as time
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate()

    # Convert to base64
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64

# ============================================================
# 4. MAIN SCRIPT
# ============================================================

def main():
    # List JSON files
    files = list_json_files()
    if not files:
        print("No JSON files found in current directory.")
        return

    print("Available JSON files:")
    for idx, f in enumerate(files):
        print(f"{idx+1}: {f}")

    choice = input("Enter the number of the file to backtest: ")
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(files):
            print("Invalid selection.")
            return
    except ValueError:
        print("Please enter a number.")
        return

    filepath = files[idx]
    print(f"Loading {filepath}...")
    data = load_data(filepath)

    # Extract symbol and date from filename (assuming format like XAUUSD_2026-09-02_M1.json)
    # or we can parse from data.
    # We'll use the filename base.
    base = os.path.splitext(filepath)[0]
    parts = base.split('_')
    if len(parts) >= 2:
        symbol = parts[0]
        date_str = parts[1]
    else:
        symbol = "UNKNOWN"
        date_str = "UNKNOWN"

    # Set parameters (same as Pine script defaults)
    range_session = "0930-0936"
    trade_session = "0930-1130"
    tp_pct = 0.005   # 0.5%
    sl_pct = 0.0025  # 0.25%

    print(f"Backtesting {symbol} on {date_str}...")
    trades, equity_curve = backtest_orb(data, range_session, trade_session, tp_pct, sl_pct)

    # Save trades to JSON
    trades_file = f"trades_{symbol}_{date_str}.json"
    with open(trades_file, 'w') as f:
        json.dump(trades, f, indent=2)
    print(f"Trades saved to {trades_file}")

    # Generate HTML report
    report_file = f"report_{symbol}_{date_str}.html"
    generate_html_report(trades, equity_curve, symbol, date_str, report_file)
    print(f"Report saved to {report_file}")

    # Optionally open in browser
    webbrowser.open(report_file)

if __name__ == "__main__":
    main()