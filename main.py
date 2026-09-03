import MetaTrader5 as mt5
from datetime import datetime, timedelta, time
import math

# ----------------------------------------------------------------------
# User inputs
# ----------------------------------------------------------------------
symbol = input("Enter symbol (e.g. XAUUSD): ").strip().upper()
days = int(input("Enter number of days to backtest: "))
balance = float(input("Enter starting balance (account currency): "))
lot = float(input("Enter lot size per trade: "))

# ----------------------------------------------------------------------
# Connect to MT5
# ----------------------------------------------------------------------
if not mt5.initialize():
    print("MT5 initialization failed")
    quit()

# Check if symbol exists
symbol_info = mt5.symbol_info(symbol)
if symbol_info is None:
    print(f"Symbol {symbol} not found")
    mt5.shutdown()
    quit()

# Ensure the symbol is selected in Market Watch (optional)
if not symbol_info.visible:
    if not mt5.symbol_select(symbol, True):
        print(f"Failed to select {symbol}")
        mt5.shutdown()
        quit()

# ----------------------------------------------------------------------
# Fetch historical 1-minute data
# ----------------------------------------------------------------------
# We need data from (today - days) to now, but we'll fetch a bit extra to cover weekends/holidays
end_date = datetime.now()
start_date = end_date - timedelta(days=days + 10)  # extra buffer

rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start_date, end_date)
if rates is None or len(rates) == 0:
    print("Failed to get historical data")
    mt5.shutdown()
    quit()

# Convert to list of dictionaries for easier handling
bars = []
for r in rates:
    bars.append({
        'time': datetime.fromtimestamp(r['time']),
        'open': r['open'],
        'high': r['high'],
        'low': r['low'],
        'close': r['close'],
    })

# Group bars by trading date (ignore weekends, but we'll filter later)
from collections import defaultdict
bars_by_date = defaultdict(list)
for bar in bars:
    # Only consider bars between 09:30 and 11:30 (server time)
    t = bar['time'].time()
    if time(9, 30) <= t < time(11, 30):
        bars_by_date[bar['time'].date()].append(bar)

# Sort dates and keep only the most recent 'days' days that have data
dates = sorted(bars_by_date.keys())
if len(dates) > days:
    dates = dates[-days:]

print(f"\nBacktesting {len(dates)} trading days for {symbol}")

# ----------------------------------------------------------------------
# Strategy parameters (fixed)
# ----------------------------------------------------------------------
ORB_START = time(9, 30)
ORB_END = time(9, 36)          # includes bars 09:30-09:35 (6 bars)
TRADE_END = time(11, 30)       # last bar open < 11:30 (i.e. 11:29)
TP_PCT = 0.005                 # 0.5%
SL_PCT = 0.0025                # 0.25%

contract_size = symbol_info.trade_contract_size
if contract_size == 0:
    print("Contract size is zero, cannot compute profit. Exiting.")
    mt5.shutdown()
    quit()

# ----------------------------------------------------------------------
# Helper to compute margin for a trade
# ----------------------------------------------------------------------
def compute_margin(order_type, price):
    """Return required margin for a trade, or None if error."""
    if order_type == 'buy':
        mt5_order_type = mt5.ORDER_TYPE_BUY
    else:
        mt5_order_type = mt5.ORDER_TYPE_SELL
    margin = mt5.order_calc_margin(mt5_order_type, symbol, lot, price)
    if margin is None:
        return None
    return margin

# ----------------------------------------------------------------------
# Main backtest loop
# ----------------------------------------------------------------------
trades = []
current_balance = balance

for day in dates:
    day_bars = bars_by_date[day]
    if len(day_bars) < 7:   # need at least 6 ORB bars + 1 breakout bar
        continue

    # The bars are already sorted chronologically
    # First 6 bars = opening range (09:30-09:35)
    orb_bars = day_bars[:6]
    orb_high = max(b['high'] for b in orb_bars)
    orb_low = min(b['low'] for b in orb_bars)

    # Previous close for the first breakout bar (close of the last ORB bar)
    prev_close = orb_bars[-1]['close']

    trade_active = False
    entry_price = None
    direction = 0          # 1 = long, -1 = short
    tp_price = None
    sl_price = None
    exit_price = None
    exit_reason = None

    # Iterate over breakout bars (from index 6 onwards)
    for i in range(6, len(day_bars)):
        bar = day_bars[i]

        if not trade_active:
            # Check for long breakout
            if bar['close'] > orb_high and prev_close <= orb_high:
                # Check margin
                margin = compute_margin('buy', bar['close'])
                if margin is None:
                    print(f"Margin calculation failed on {day} for long entry. Skipping trade.")
                    break
                if margin > current_balance:
                    print(f"Insufficient margin on {day} for long entry (need {margin:.2f}, have {current_balance:.2f}). Skipping trade.")
                    break
                entry_price = bar['close']
                direction = 1
                tp_price = entry_price * (1 + TP_PCT)
                sl_price = entry_price * (1 - SL_PCT)
                trade_active = True
                # do not check TP/SL on entry bar
            # Check for short breakout
            elif bar['close'] < orb_low and prev_close >= orb_low:
                margin = compute_margin('sell', bar['close'])
                if margin is None:
                    print(f"Margin calculation failed on {day} for short entry. Skipping trade.")
                    break
                if margin > current_balance:
                    print(f"Insufficient margin on {day} for short entry (need {margin:.2f}, have {current_balance:.2f}). Skipping trade.")
                    break
                entry_price = bar['close']
                direction = -1
                tp_price = entry_price * (1 - TP_PCT)
                sl_price = entry_price * (1 + SL_PCT)
                trade_active = True

            # update previous close for next bar
            prev_close = bar['close']

        else:
            # Check exit conditions (TP first, then SL)
            if direction == 1:   # long
                if bar['high'] >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    break
                elif bar['low'] <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    break
            else:                # short
                if bar['low'] <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    break
                elif bar['high'] >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    break
            # No exit yet, continue

    # If trade is still active at end of session, close at last bar's close
    if trade_active and exit_price is None:
        exit_price = day_bars[-1]['close']
        exit_reason = 'EOD'

    # Record the trade if one was opened
    if trade_active:
        # Compute profit in account currency (assumes USD account, or symbol quote = account currency)
        # For XAUUSD: profit = (exit - entry) * direction * lot * contract_size
        profit = (exit_price - entry_price) * direction * lot * contract_size
        current_balance += profit

        trades.append({
            'date': day,
            'direction': 'LONG' if direction == 1 else 'SHORT',
            'entry': entry_price,
            'exit': exit_price,
            'exit_reason': exit_reason,
            'profit': profit,
            'balance_after': current_balance,
        })

# ----------------------------------------------------------------------
# Output results
# ----------------------------------------------------------------------
print("\n" + "="*60)
print(f"Backtest Results for {symbol} ({days} days, lot={lot})")
print("="*60)
if not trades:
    print("No trades were executed.")
else:
    total_profit = sum(t['profit'] for t in trades)
    wins = [t for t in trades if t['profit'] > 0]
    losses = [t for t in trades if t['profit'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    print(f"Number of trades: {len(trades)}")
    print(f"Winning trades:   {len(wins)}")
    print(f"Losing trades:    {len(losses)}")
    print(f"Win rate:         {win_rate:.1f}%")
    print(f"Total profit:     {total_profit:.2f}")
    print(f"Final balance:    {current_balance:.2f}")

    print("\nTrade details:")
    for t in trades:
        print(f"{t['date']}  {t['direction']:5s}  Entry={t['entry']:.5f}  Exit={t['exit']:.5f}  Reason={t['exit_reason']:3s}  Profit={t['profit']:+.2f}")

mt5.shutdown()