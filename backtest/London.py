import json
import os
import glob
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

LONDON_TZ = ZoneInfo("Europe/London")   # changed from NY_TZ

RANGE_START = datetime.time(9, 31)
RANGE_END   = datetime.time(9, 36)   # exclusive
TRADE_START = datetime.time(9, 30)
TRADE_END   = datetime.time(11, 30)  # exclusive

TP_PCT = 0.0025   # 0.5 %
SL_PCT = 0.0025  # 0.25 %

CONTRACT_SIZE = 100  # XAUUSD = 100 oz per lot


def calc_margin(lots, price, leverage):
    return (lots * CONTRACT_SIZE * price) / leverage


def calc_lot_size(balance, leverage, price, risk_pct=0.02):
    margin_per_lot = calc_margin(1.0, price, leverage)
    available = balance * risk_pct
    lots = available / margin_per_lot
    lots = round(lots, 2)
    return max(lots, 0.01)


def load_bars(filepath):
    with open(filepath, 'r') as f:
        raw = json.load(f)
    bars = []
    for r in raw:
        dt = datetime.datetime.fromisoformat(r['time'])
        bars.append({
            'time':  dt,
            'open':  r['open'],
            'high':  r['high'],
            'low':   r['low'],
            'close': r['close'],
        })
    bars.sort(key=lambda b: b['time'])
    return bars


def run_orb(bars, lot_size):
    orb_high = None
    orb_low  = None
    range_locked   = False
    range_building = False

    trade_active = False
    trade_long   = False
    entry_price  = None
    tp_price     = None
    sl_price     = None
    day_done     = False

    result = {
        'orb_high': None, 'orb_low': None,
        'range_bars': [],
        'signal': None, 'entry': None, 'tp': None, 'sl': None,
        'exit_price': None, 'exit_time': None, 'exit_type': None,
        'outcome': None, 'lots': lot_size, 'pnl': 0.0,
        'margin': 0.0, 'free_margin': 0.0,
    }

    for i, bar in enumerate(bars):
        t = bar['time'].time()
        in_range = RANGE_START <= t < RANGE_END
        in_trade = TRADE_START <= t < TRADE_END

        # ── session start detection (new day) ──
        if i == 0 or bars[i]['time'].date() != bars[i - 1]['time'].date():
            orb_high = None;  orb_low  = None
            range_locked = False;  range_building = False
            trade_active = False;  day_done = False
            entry_price = tp_price = sl_price = None
            result = {
                'orb_high': None, 'orb_low': None,
                'range_bars': [],
                'signal': None, 'entry': None, 'tp': None, 'sl': None,
                'exit_price': None, 'exit_time': None, 'exit_type': None,
                'outcome': None, 'lots': lot_size, 'pnl': 0.0,
                'margin': 0.0, 'free_margin': 0.0,
            }

        # ── build range ──
        if in_range and not range_locked:
            if orb_high is None:
                orb_high = bar['high']
                orb_low  = bar['low']
                range_building = True
            else:
                orb_high = max(orb_high, bar['high'])
                orb_low  = min(orb_low,  bar['low'])
            result['range_bars'].append(bar['time'].isoformat())

        # lock range
        if not in_range and range_building and not range_locked:
            range_locked = True
            range_building = False
            result['orb_high'] = orb_high
            result['orb_low']  = orb_low

        # ── manage open trade ──
        if trade_active:
            hit_tp = (trade_long and bar['high'] >= tp_price) or (not trade_long and bar['low'] <= tp_price)
            hit_sl = (trade_long and bar['low']  <= sl_price) or (not trade_long and bar['high'] >= sl_price)

            if hit_tp:
                exit_p = tp_price
                pnl = (exit_p - entry_price) * lot_size * CONTRACT_SIZE if trade_long \
                    else (entry_price - exit_p) * lot_size * CONTRACT_SIZE
                result['exit_price'] = exit_p
                result['exit_time']  = bar['time'].isoformat()
                result['exit_type']  = 'TP'
                result['outcome']    = 'WIN'
                result['pnl']        = round(pnl, 2)
                trade_active = False
                day_done = True
            elif hit_sl:
                exit_p = sl_price
                pnl = (exit_p - entry_price) * lot_size * CONTRACT_SIZE if trade_long \
                    else (entry_price - exit_p) * lot_size * CONTRACT_SIZE
                result['exit_price'] = exit_p
                result['exit_time']  = bar['time'].isoformat()
                result['exit_type']  = 'SL'
                result['outcome']    = 'LOSS'
                result['pnl']        = round(pnl, 2)
                trade_active = False
                day_done = True

        # ── breakout detection ──
        if not trade_active and not day_done and range_locked and in_trade and i > 0:
            prev_close = bars[i - 1]['close']
            if bar['close'] > orb_high and prev_close <= orb_high:
                trade_active = True;  trade_long = True
                entry_price = bar['close']
                tp_price    = entry_price * (1 + TP_PCT)
                sl_price    = entry_price * (1 - SL_PCT)
                margin = calc_margin(lot_size, entry_price, leverage)
                result['signal'] = 'LONG'
                result['entry']  = {'price': entry_price, 'time': bar['time'].isoformat()}
                result['tp']     = tp_price
                result['sl']     = sl_price
                result['margin'] = round(margin, 2)

            elif bar['close'] < orb_low and prev_close >= orb_low:
                trade_active = True;  trade_long = False
                entry_price = bar['close']
                tp_price    = entry_price * (1 - TP_PCT)
                sl_price    = entry_price * (1 + SL_PCT)
                margin = calc_margin(lot_size, entry_price, leverage)
                result['signal'] = 'SHORT'
                result['entry']  = {'price': entry_price, 'time': bar['time'].isoformat()}
                result['tp']     = tp_price
                result['sl']     = sl_price
                result['margin'] = round(margin, 2)

    if result['outcome'] is None and result['signal'] is not None:
        result['outcome'] = 'OPEN'

    return result


def chart_orb(bars, result, symbol, date_str, out_dir):
    clean_bars = [{**b, 'time': b['time'].replace(tzinfo=None)} for b in bars]
    bars = clean_bars

    df = pd.DataFrame(bars)
    df['time'] = df['time'].apply(lambda t: t.replace(tzinfo=None) if hasattr(t, 'tzinfo') else t)
    df.set_index('time', inplace=True)

    orb_h = result['orb_high']
    orb_l = result['orb_low']
    sig   = result['signal']

    trade_bars = [b for b in bars if TRADE_START <= b['time'].time() < TRADE_END]
    if not trade_bars:
        return
    t0 = trade_bars[0]['time']
    t1 = trade_bars[-1]['time']
    mask = (df.index >= t0) & (df.index <= t1)
    ch = df.loc[mask].copy()
    if ch.empty:
        return

    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')

    width = pd.Timedelta(minutes=0.4)
    for idx, row in ch.iterrows():
        color = '#00d4aa' if row['close'] >= row['open'] else '#ff4757'
        ax.bar(idx, row['close'] - row['open'], width, bottom=row['open'],
               color=color, edgecolor=color, linewidth=0.5)
        ax.vlines(idx, row['low'], row['high'], color=color, linewidth=0.7)

    if orb_h is not None and orb_l is not None:
        range_end = t0 + pd.Timedelta(minutes=5)
        ax.axhspan(orb_l, orb_h, xmin=0, xmax=(range_end - t0).total_seconds() / max((t1 - t0).total_seconds(), 1),
                   alpha=0.15, color='#3498db', zorder=0)
        ax.axhline(orb_h, color='#3498db', linewidth=1.2, linestyle='--', alpha=0.8, label=f'ORB High {orb_h:.2f}')
        ax.axhline(orb_l, color='#e74c3c', linewidth=1.2, linestyle='--', alpha=0.8, label=f'ORB Low  {orb_l:.2f}')

    if sig and result['entry']:
        ep = result['entry']['price']
        tp = result['tp']
        sl = result['sl']
        entry_time = datetime.datetime.fromisoformat(result['entry']['time']).replace(tzinfo=None)

        ax.axhline(ep, color='#f1c40f', linewidth=1, linestyle=':', alpha=0.9, label=f'Entry {ep:.2f}')
        ax.axhline(tp, color='#2ecc71', linewidth=1.2, linestyle='--', alpha=0.9, label=f'TP {tp:.2f}')
        ax.axhline(sl, color='#e74c3c', linewidth=1.2, linestyle='--', alpha=0.9, label=f'SL {sl:.2f}')

        marker = '^' if sig == 'LONG' else 'v'
        mcolor  = '#00ff88' if sig == 'LONG' else '#ff4757'
        ax.plot(entry_time, ep, marker=marker, color=mcolor, markersize=14, zorder=10)

    if result['exit_time']:
        ex_t = datetime.datetime.fromisoformat(result['exit_time']).replace(tzinfo=None)
        ex_p = result['exit_price']
        ecolor = '#2ecc71' if result['outcome'] == 'WIN' else '#e74c3c'
        ax.plot(ex_t, ex_p, 'x', color=ecolor, markersize=14, markeredgewidth=3, zorder=10)

    pnl = result.get('pnl', 0)
    lots = result.get('lots', 0)
    ax.set_title(f'{symbol}  {date_str}  |  ORB {sig or "NO TRADE"}  |  {result["outcome"] or "—"}  |  {lots} lots  P&L {pnl:+.2f}',
                 color='white', fontsize=13, fontweight='bold')
    ax.set_ylabel('Price', color='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(colors='white')
    ax.legend(loc='upper left', fontsize=9, facecolor='#1a1a2e', edgecolor='#444', labelcolor='white')
    plt.xticks(rotation=45)
    plt.tight_layout()

    png_path = os.path.join(out_dir, f'{symbol}_{date_str}_ORB.png')
    fig.savefig(png_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return png_path


def build_html(all_results, out_dir, init_balance, leverage, init_free):
    rows = ''
    for r in all_results:
        sig = r['signal'] or '—'
        outcome = r['outcome'] or '—'
        oc = '#2ecc71' if outcome == 'WIN' else '#e74c3c' if outcome == 'LOSS' else '#f39c12'
        oh = f"{r['orb_high']:.2f}" if r['orb_high'] else '—'
        ol = f"{r['orb_low']:.2f}"  if r['orb_low']  else '—'
        sc = '#00ff88' if sig == 'LONG' else '#ff4757' if sig == 'SHORT' else '#888'
        ep = f"{r['entry']['price']:.2f}" if r['entry'] else '—'
        tp = f"{r['tp']:.2f}" if r['tp'] else '—'
        sl = f"{r['sl']:.2f}" if r['sl'] else '—'
        ex = f"{r['exit_price']:.2f}" if r['exit_price'] else '—'
        et = r['exit_type'] or '—'
        lots = r.get('lots', 0)
        pnl = r.get('pnl', 0)
        margin = r.get('margin', 0)
        pnl_color = '#2ecc71' if pnl > 0 else '#e74c3c' if pnl < 0 else '#888'
        rows += f"""<tr>
  <td>{r['symbol']}</td><td>{r['date']}</td>
  <td>{oh}</td><td>{ol}</td>
  <td style="color:{sc}">{sig}</td>
  <td>{lots}</td>
  <td>{ep}</td><td>{tp}</td><td>{sl}</td>
  <td>{margin:.2f}</td>
  <td>{ex}</td><td>{et}</td>
  <td style="color:{pnl_color};font-weight:bold">{pnl:+.2f}</td>
  <td style="color:{oc};font-weight:bold">{outcome}</td>
</tr>"""

    total_pnl = sum(r.get('pnl', 0) for r in all_results)
    final_balance = init_balance + total_pnl
    wins = sum(1 for r in all_results if r['outcome'] == 'WIN')
    losses = sum(1 for r in all_results if r['outcome'] == 'LOSS')
    trades = sum(1 for r in all_results if r['signal'] is not None)
    win_rate = (wins / trades * 100) if trades > 0 else 0
    pnl_color = '#2ecc71' if total_pnl >= 0 else '#e74c3c'
    bal_color = '#2ecc71' if final_balance >= init_balance else '#e74c3c'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>ORB Strategy Results</title>
<style>
  body {{ background:#0f0f23; color:#ccc; font-family:Consolas,monospace; padding:20px; }}
  h1 {{ color:#f1c40f; text-align:center; }}
  h2 {{ color:#3498db; margin-top:30px; }}
  .summary {{ display:flex; gap:20px; justify-content:center; flex-wrap:wrap; margin:20px 0; }}
  .card {{ background:#1a1a2e; border:1px solid #333; border-radius:8px; padding:15px 25px; text-align:center; min-width:160px; }}
  .card .label {{ color:#888; font-size:12px; }}
  .card .value {{ color:#f1c40f; font-size:22px; font-weight:bold; margin-top:5px; }}
  table {{ border-collapse:collapse; width:100%; margin-top:20px; }}
  th {{ background:#1a1a2e; color:#f1c40f; padding:10px; border:1px solid #333; font-size:12px; }}
  td {{ padding:8px 10px; border:1px solid #333; text-align:center; }}
  tr:hover {{ background:#1a1a2e; }}
  .charts {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin-top:30px; }}
  .charts img {{ max-width:600px; border:1px solid #333; border-radius:6px; }}
</style></head><body>
<h1>ORB - Opening Range Breakout Results</h1>

<div class="summary">
  <div class="card"><div class="label">Starting Balance</div><div class="value">${init_balance:,.2f}</div></div>
  <div class="card"><div class="label">Final Balance</div><div class="value" style="color:{bal_color}">${final_balance:,.2f}</div></div>
  <div class="card"><div class="label">Total P&L</div><div class="value" style="color:{pnl_color}">{total_pnl:+.2f}</div></div>
  <div class="card"><div class="label">Leverage</div><div class="value">1:{leverage}</div></div>
  <div class="card"><div class="label">Trades</div><div class="value">{trades}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{win_rate:.1f}%</div></div>
  <div class="card"><div class="label">Wins / Losses</div><div class="value">{wins} / {losses}</div></div>
</div>

<h2>Trade Log</h2>
<table>
<tr><th>Symbol</th><th>Date</th><th>ORB High</th><th>ORB Low</th>
<th>Signal</th><th>Lots</th><th>Entry</th><th>TP</th><th>SL</th>
<th>Margin</th><th>Exit</th><th>Type</th><th>P&L</th><th>Outcome</th></tr>
{rows}</table>

<h2>Charts</h2>
<div class="charts">"""

    for r in all_results:
        png = r.get('png')
        if png and os.path.exists(png):
            rel = os.path.relpath(png, out_dir)
            html += f'\n<img src="{rel}" alt="{r["date"]}">'

    html += "\n</div></body></html>"
    html_path = os.path.join(out_dir, 'orb_results.html')
    with open(html_path, 'w') as f:
        f.write(html)
    return html_path


def main():
    global leverage

    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_files = sorted(glob.glob(os.path.join(script_dir, '*_M1.json')))
    if not json_files:
        print('No *_M1.json files found.')
        return

    # ── user inputs ──
    print("+----------------------------------+")
    print("|       ORB BACKTEST - SETUP       |")
    print("+----------------------------------+")
    balance = float(input('Enter account balance (e.g. 1000): '))
    lev_str = input('Enter leverage (e.g. 500 for 1:500): ')
    leverage = int(lev_str)

    print(f'\nBalance: ${balance:,.2f}  |  Leverage: 1:{leverage}')
    print(f'Found {len(json_files)} file(s):')
    for f in json_files:
        print(f'  {os.path.basename(f)}')

    all_results = []
    running_balance = balance

    for filepath in json_files:
        fname = os.path.basename(filepath)
        base = fname.replace('_M1.json', '')
        dash = base.find('_')
        if dash > 0:
            symbol   = base[:dash]
            date_str = base[dash+1:]
        else:
            symbol   = base
            date_str = 'unknown'

        bars = load_bars(filepath)
        print(f'\nProcessing {symbol} {date_str} — {len(bars)} bars')

        # calculate lot size from current balance
        mid_price = bars[len(bars)//2]['close'] if bars else 2000
        lot_size = calc_lot_size(running_balance, leverage, mid_price)
        print(f'  Balance: ${running_balance:,.2f}  Lot size: {lot_size}')

        result = run_orb(bars, lot_size)
        result['symbol'] = symbol
        result['date']   = date_str

        # calculate free margin
        entry_p = result['entry']['price'] if result['entry'] else mid_price
        margin = calc_margin(lot_size, entry_p, leverage)
        result['margin'] = round(margin, 2)
        result['free_margin'] = round(running_balance - margin, 2)

        # update running balance
        running_balance += result.get('pnl', 0)
        result['balance_after'] = round(running_balance, 2)

        # save individual JSON
        json_out = os.path.join(script_dir, f'{symbol}_{date_str}_ORB.json')
        save_data = {k: v for k, v in result.items() if k != 'range_bars'}
        save_data['range_bar_count'] = len(result['range_bars'])
        with open(json_out, 'w') as f:
            json.dump(save_data, f, indent=2, default=str)

        png = chart_orb(bars, result, symbol, date_str, script_dir)
        result['png'] = png

        pnl = result.get('pnl', 0)
        pnl_s = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        if result['orb_high'] is not None:
            print(f'  ORB: {result["orb_high"]:.2f}/{result["orb_low"]:.2f}')
        else:
            print('  ORB: No range built')
        print(f'  {result["signal"] or "NO TRADE":>5}  {lot_size} lots  Margin: ${margin:.2f}  P&L: {pnl_s}  Balance: ${running_balance:,.2f}')
        all_results.append(result)

    # ── summary ──
    total_pnl = running_balance - balance
    wins   = sum(1 for r in all_results if r['outcome'] == 'WIN')
    losses = sum(1 for r in all_results if r['outcome'] == 'LOSS')
    opens  = sum(1 for r in all_results if r['outcome'] == 'OPEN')
    trades = sum(1 for r in all_results if r['signal'] is not None)
    print(f'\n{"="*50}')
    print(f'Starting Balance: ${balance:,.2f}')
    print(f'Final Balance:    ${running_balance:,.2f}')
    print(f'Total P&L:        {total_pnl:+.2f}')
    print(f'Trades: {trades}  |  WIN: {wins}  LOSS: {losses}  OPEN: {opens}')
    if trades > 0:
        print(f'Win rate: {wins/trades*100:.1f}%')

    html_path = build_html(all_results, script_dir, balance, leverage, balance)
    print(f'\nHTML report: {html_path}')
    print('Done.')


if __name__ == '__main__':
    main()