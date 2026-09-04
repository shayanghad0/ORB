Add this Trading date 

| Market | Local Opening Time |
| :--- | :--- |
| Sydney (ASX) | 10:00 AM |
| Tokyo (TSE) | 9:00 AM |
| London (LSE) | 8:00 AM |
| New York (NYSE) | 9:30 AM |


Based on **New York Time (ET)** and the DST status as of **September 2026**:

| Market | Opening Time in New York Time (ET) |
| :--- | :--- |
| Sydney (ASX) | 8:00 PM **(previous day)** |
| Tokyo (TSE) | 8:00 PM **(previous day)** |
| London (LSE) | 3:00 AM |
| New York (NYSE) | 9:30 AM |

> **Note:** These conversions assume DST is active in the US (EDT, UTC-4), the UK (BST, UTC+1), and Australia is on standard time (AEST, UTC+10). Times shift by ±1 hour when any region changes its DST clocks on different dates.

keep the timezone and when on time zone we are in this time trade 

## Completed Features

- [x] Live trading bot with MT5 (`orb_live.py`)
- [x] Trade logging to JSON database (`db.py`)
- [x] Daily HTML reports (`db/{date}/index.html`)
- [x] All-trades HTML report (`all.html`)
- [x] Auto-export on Ctrl+C
- [x] Backtest engine (`orb_strategy.py`) 







Make a Live Trading bot on NewYork Time zone like backtest 
use strategy and find signal then enter didnt set a TP or SL update with Milisecend and when price is tp 1  tp2 or sl do action i need

with this 100% like indicator and 100% pythoncode backtest


if use claude

```pinescript
// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © shayanghad0 (modified for time‑based ORB with fixed range window)

//@version=5
indicator("ORB - Opening Range Breakout (Time-based)", overlay=true, max_labels_count=500, max_lines_count=500)

// ─────────────────────────────────────────────
// INPUTS — Strategy
// ─────────────────────────────────────────────
// Set the end time ONE MINUTE later than your desired last bar.
// Example: to include the 09:35 bar, use "0930-0936"
range_session = input.session("0930-0936", "Opening Range Window (exchange time)", 
                  tooltip="Bars with open time >= start and < end are included. To include the 09:35 bar, set end to 09:36.")
trade_session = input.session("0930-1130", "Trading Window (exchange time)",
                  tooltip="Breakout signals are only generated within this window.")

tp_pct = input.float(0.5, "TP %", minval=0.01, step=0.05, group="Strategy",
         tooltip="Take Profit as % of entry price.") / 100
sl_pct = input.float(0.25, "SL %", minval=0.01, step=0.05, group="Strategy",
         tooltip="Stop Loss as % of entry price.") / 100

// ─────────────────────────────────────────────
// INPUTS — Display
// ─────────────────────────────────────────────
show_range    = input.bool(true, "Show Opening Range Box",      group="Display")
show_labels   = input.bool(true, "Show Entry / TP / SL labels", group="Display")
show_signals  = input.bool(true, "Show Breakout Signal Arrow",  group="Display")
show_bg       = input.bool(true, "Show background highlight",   group="Display")

label_offset  = input.int(40, "Label offset (bars right of signal)",
                  minval=0, maxval=500, group="Label Position",
                  tooltip="Increase to push labels further right.")
label_size    = input.string("small", "Label size",
                  options=["tiny","small","normal","large"], group="Label Position")
line_length   = input.int(500, "Line length (bars to the right)",
                  minval=10, maxval=5000, group="Line Length")

col_bull      = input.color(color.new(color.lime, 40), "Bullish color", group="Colors")
col_bear      = input.color(color.new(color.red,  40), "Bearish color", group="Colors")
col_entry     = input.color(color.yellow,              "Entry color",    group="Colors")
col_tp        = input.color(color.lime,                "TP color",       group="Colors")
col_sl        = input.color(color.red,                 "SL color",       group="Colors")

// ─────────────────────────────────────────────
// LABEL SIZE
// ─────────────────────────────────────────────
lsize = switch label_size
    "tiny"   => size.tiny
    "normal" => size.normal
    "large"  => size.large
    =>           size.small

// ─────────────────────────────────────────────
// SESSION DETECTION
// ─────────────────────────────────────────────
in_trade    = not na(time(timeframe.period, trade_session))
in_range    = not na(time(timeframe.period, range_session))

// Detect first bar of the trading session (for reset)
var bool session_start = false
if in_trade and not in_trade[1]
    session_start := true
else
    session_start := false

// ─────────────────────────────────────────────
// STATE VARIABLES
// ─────────────────────────────────────────────
var float orb_high          = na
var float orb_low           = na
var bool  range_locked      = false
var bool  range_building    = false
var int   range_start_bar   = na
var int   range_bar_count   = 0       // for debugging / display

var bool  trade_active      = false
var bool  trade_long        = false
var float entry_price       = na
var float tp_price          = na
var float sl_price          = na
var bool  day_done          = false
var int   signal_bar        = na

var box   bx_range          = na
var line  ln_entry          = na
var line  ln_tp             = na
var line  ln_sl             = na
var label lb_entry          = na
var label lb_tp             = na
var label lb_sl             = na

// ─────────────────────────────────────────────
// RESET ON NEW SESSION
// ─────────────────────────────────────────────
if session_start
    orb_high          := na
    orb_low           := na
    range_locked      := false
    range_building    := false
    range_start_bar   := na
    range_bar_count   := 0
    trade_active      := false
    entry_price       := na
    tp_price          := na
    sl_price          := na
    day_done          := false
    signal_bar        := na
    
    line.delete(ln_entry)
    ln_entry := na
    line.delete(ln_tp)
    ln_tp    := na
    line.delete(ln_sl)
    ln_sl    := na
    label.delete(lb_entry)
    lb_entry := na
    label.delete(lb_tp)
    lb_tp    := na
    label.delete(lb_sl)
    lb_sl    := na
    box.delete(bx_range)
    bx_range := na

// ─────────────────────────────────────────────
// BUILD OPENING RANGE (time‑based)
// ─────────────────────────────────────────────
if in_range and not range_locked
    if na(orb_high)
        orb_high := high
        orb_low  := low
        range_building := true
        range_start_bar := bar_index
        range_bar_count := 1
    else
        orb_high := math.max(orb_high, high)
        orb_low  := math.min(orb_low, low)
        range_bar_count += 1

// Lock the range when we leave the range window
if not in_range and range_building and not range_locked
    range_locked := true
    if show_range and not na(range_start_bar)
        box.delete(bx_range)
        // End bar is the last bar inside the window = bar_index - 1
        bx_range := box.new(range_start_bar, orb_high, bar_index - 1, orb_low, border_color=color.gray, bgcolor=color.new(color.gray, 75))

// ─────────────────────────────────────────────
// SIGNAL DETECTION (only after range is locked)
// ─────────────────────────────────────────────
bullish_bo = range_locked and not day_done and not trade_active and in_trade
             and close > orb_high and close[1] <= orb_high

bearish_bo = range_locked and not day_done and not trade_active and in_trade
             and close < orb_low and close[1] >= orb_low

// ─────────────────────────────────────────────
// ENTER — LONG
// ─────────────────────────────────────────────
if bullish_bo
    trade_active := true
    trade_long   := true
    entry_price  := close
    tp_price     := entry_price * (1 + tp_pct)
    sl_price     := entry_price * (1 - sl_pct)
    signal_bar   := bar_index

    line.delete(ln_entry)
    ln_entry := na
    line.delete(ln_tp)
    ln_tp    := na
    line.delete(ln_sl)
    ln_sl    := na
    label.delete(lb_entry)
    lb_entry := na
    label.delete(lb_tp)
    lb_tp    := na
    label.delete(lb_sl)
    lb_sl    := na

    int end_bar  = bar_index + line_length
    ln_entry := line.new(bar_index, entry_price, end_bar, entry_price,
                 color=col_entry, width=1, style=line.style_dashed, extend=extend.none)
    ln_tp    := line.new(bar_index, tp_price,    end_bar, tp_price,
                 color=col_tp,    width=2, style=line.style_dashed, extend=extend.none)
    ln_sl    := line.new(bar_index, sl_price,    end_bar, sl_price,
                 color=col_sl,    width=2, style=line.style_dashed, extend=extend.none)

    if show_labels
        lb_entry := label.new(bar_index + label_offset, entry_price,
                     "ENTRY " + str.tostring(entry_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_entry, textcolor=color.black, size=lsize)
        lb_tp    := label.new(bar_index + label_offset, tp_price,
                     "TP +0.5% " + str.tostring(tp_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_tp, textcolor=color.black, size=lsize)
        lb_sl    := label.new(bar_index + label_offset, sl_price,
                     "SL -0.25% " + str.tostring(sl_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_sl, textcolor=color.black, size=lsize)

    if show_signals
        label.new(bar_index, low - (high - low),
             "▲ LONG\n" + str.tostring(close, "#.#####"),
             style=label.style_label_up, color=col_bull,
             textcolor=color.black, size=size.normal)

// ─────────────────────────────────────────────
// ENTER — SHORT
// ─────────────────────────────────────────────
if bearish_bo
    trade_active := true
    trade_long   := false
    entry_price  := close
    tp_price     := entry_price * (1 - tp_pct)
    sl_price     := entry_price * (1 + sl_pct)
    signal_bar   := bar_index

    line.delete(ln_entry)
    ln_entry := na
    line.delete(ln_tp)
    ln_tp    := na
    line.delete(ln_sl)
    ln_sl    := na
    label.delete(lb_entry)
    lb_entry := na
    label.delete(lb_tp)
    lb_tp    := na
    label.delete(lb_sl)
    lb_sl    := na

    int end_bar  = bar_index + line_length
    ln_entry := line.new(bar_index, entry_price, end_bar, entry_price,
                 color=col_entry, width=1, style=line.style_dashed, extend=extend.none)
    ln_tp    := line.new(bar_index, tp_price,    end_bar, tp_price,
                 color=col_tp,    width=2, style=line.style_dashed, extend=extend.none)
    ln_sl    := line.new(bar_index, sl_price,    end_bar, sl_price,
                 color=col_sl,    width=2, style=line.style_dashed, extend=extend.none)

    if show_labels
        lb_entry := label.new(bar_index + label_offset, entry_price,
                     "ENTRY " + str.tostring(entry_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_entry, textcolor=color.black, size=lsize)
        lb_tp    := label.new(bar_index + label_offset, tp_price,
                     "TP -0.5% " + str.tostring(tp_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_tp, textcolor=color.black, size=lsize)
        lb_sl    := label.new(bar_index + label_offset, sl_price,
                     "SL +0.25% " + str.tostring(sl_price, "#.#####"),
                     style=label.style_label_left,
                     color=col_sl, textcolor=color.black, size=lsize)

    if show_signals
        label.new(bar_index, high + (high - low),
             "▼ SHORT\n" + str.tostring(close, "#.#####"),
             style=label.style_label_down, color=col_bear,
             textcolor=color.black, size=size.normal)

// ─────────────────────────────────────────────
// MANAGE OPEN TRADE — TP / SL HIT
// ─────────────────────────────────────────────
if trade_active
    hit_tp   = trade_long     and high >= tp_price
    hit_sl   = trade_long     and low  <= sl_price
    hit_tp_s = not trade_long and low  <= tp_price
    hit_sl_s = not trade_long and high >= sl_price

    if hit_tp or hit_tp_s
        _y     = trade_long ? high : low
        _style = trade_long ? label.style_label_down : label.style_label_up
        label.new(bar_index, _y, "✅ TP HIT",
             style=_style, color=color.lime, textcolor=color.black, size=size.small)
        line.delete(ln_entry)
        ln_entry := na
        line.delete(ln_tp)
        ln_tp    := na
        line.delete(ln_sl)
        ln_sl    := na
        label.delete(lb_entry)
        lb_entry := na
        label.delete(lb_tp)
        lb_tp    := na
        label.delete(lb_sl)
        lb_sl    := na
        trade_active := false
        day_done     := true

    else if hit_sl or hit_sl_s
        _y     = trade_long ? low  : high
        _style = trade_long ? label.style_label_up : label.style_label_down
        label.new(bar_index, _y, "❌ SL HIT\n⏳ Wait tomorrow",
             style=_style, color=color.red, textcolor=color.white, size=size.small)
        line.delete(ln_entry)
        ln_entry := na
        line.delete(ln_tp)
        ln_tp    := na
        line.delete(ln_sl)
        ln_sl    := na
        label.delete(lb_entry)
        lb_entry := na
        label.delete(lb_tp)
        lb_tp    := na
        label.delete(lb_sl)
        lb_sl    := na
        trade_active := false
        day_done     := true

// ─────────────────────────────────────────────
// BACKGROUND HIGHLIGHTS — CORRECTED (returns color or na)
// ─────────────────────────────────────────────
bgcolor(show_bg and in_range and not range_locked ? color.new(color.blue, 90) : na, title="Range-building bars")
bgcolor(show_bg and trade_active and trade_long ? color.new(color.lime, 95) : na, title="Long active")
bgcolor(show_bg and trade_active and not trade_long ? color.new(color.red, 95) : na, title="Short active")

// ─────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────
var table dash = table.new(position.top_right, 2, 7, border_width=1)

if barstate.islast
    table.cell(dash, 0, 0, "ORB " + range_session, bgcolor=color.navy, text_color=color.white, text_size=size.small)
    table.cell(dash, 1, 0, "",                     bgcolor=color.navy)

    table.cell(dash, 0, 1, "Range", bgcolor=color.gray, text_color=color.white, text_size=size.tiny)
    table.cell(dash, 1, 1,
         range_locked ? str.tostring(orb_high,"#.#####") + " / " + str.tostring(orb_low,"#.#####") + " (" + str.tostring(range_bar_count) + " bars)" : "Building...",
         bgcolor=color.gray, text_color=color.white, text_size=size.tiny)

    status_txt = day_done     ? "Done for today" :
                 trade_active ? (trade_long ? "LONG active" : "SHORT active") :
                 range_locked ? "Watching..."    : "Range building"
    status_col = day_done     ? color.gray :
                 trade_active ? (trade_long ? color.lime : color.red) : color.blue
    table.cell(dash, 0, 2, "Status",   bgcolor=color.black, text_color=color.white, text_size=size.tiny)
    table.cell(dash, 1, 2, status_txt, bgcolor=status_col,  text_color=color.black, text_size=size.tiny)

    table.cell(dash, 0, 3, "Entry", bgcolor=color.black, text_color=color.white,  text_size=size.tiny)
    table.cell(dash, 1, 3,
         not na(entry_price) ? str.tostring(entry_price,"#.#####") : "—",
         bgcolor=color.black, text_color=color.yellow, text_size=size.tiny)

    table.cell(dash, 0, 4, "TP  +0.5%", bgcolor=color.black, text_color=color.white, text_size=size.tiny)
    table.cell(dash, 1, 4,
         not na(tp_price) ? str.tostring(tp_price,"#.#####") : "—",
         bgcolor=color.black, text_color=color.lime, text_size=size.tiny)

    table.cell(dash, 0, 5, "SL -0.25%", bgcolor=color.black, text_color=color.white, text_size=size.tiny)
    table.cell(dash, 1, 5,
         not na(sl_price) ? str.tostring(sl_price,"#.#####") : "—",
         bgcolor=color.black, text_color=color.red, text_size=size.tiny)

    table.cell(dash, 0, 6, "RR Ratio", bgcolor=color.black, text_color=color.white,  text_size=size.tiny)
    table.cell(dash, 1, 6, "2:1",      bgcolor=color.black, text_color=color.orange, text_size=size.tiny)
```

and python code

```python
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

NY_TZ = ZoneInfo("America/New_York")

RANGE_START = datetime.time(9, 31)
RANGE_END   = datetime.time(9, 37)   # exclusive
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

```