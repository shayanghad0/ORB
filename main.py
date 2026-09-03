import MetaTrader5 as mt5
from datetime import datetime, timedelta, time
from collections import defaultdict
import sys
import time as time_module

# ----------------------------------------------------------------------
# User inputs
# ----------------------------------------------------------------------
symbol_input = input("Enter symbol (e.g. XAUUSD): ").strip().upper()
days = int(input("Enter number of days to backtest: "))
balance = float(input("Enter starting balance (account currency): "))
lot = float(input("Enter lot size per trade: "))

# ----------------------------------------------------------------------
# Connect to MT5 and login
# ----------------------------------------------------------------------
if not mt5.initialize():
    print("MT5 initialization failed, error code =", mt5.last_error())
    sys.exit(1)

print("\n--- MT5 Login ---")
login = input("Enter account login (number): ").strip()
password = input("Enter account password: ").strip()
server = input("Enter server name (optional, press Enter to skip): ").strip()

# Remove quotes if present
if password.startswith('"') and password.endswith('"'):
    password = password[1:-1]
if server.startswith('"') and server.endswith('"'):
    server = server[1:-1]

login_params = {"login": int(login), "password": password}
if server:
    login_params["server"] = server

print(f"Logging in to account {login} ...")
authorized = mt5.login(**login_params)
if not authorized:
    print("Login failed. Error code:", mt5.last_error())
    mt5.shutdown()
    sys.exit(1)

account_info = mt5.account_info()
if account_info is None:
    print("Login succeeded but failed to retrieve account info.")
    mt5.shutdown()
    sys.exit(1)

print("Login successful!")
print(f"Account: {account_info.login}")
print(f"Server:  {account_info.server}")
print(f"Balance: {account_info.balance}")
print(f"Currency:{account_info.currency}")

terminal_info = mt5.terminal_info()
if terminal_info is None or not terminal_info.connected:
    print("Terminal is not connected to the broker server.")
    mt5.shutdown()
    sys.exit(1)

# ----------------------------------------------------------------------
# Identify the correct symbol
# ----------------------------------------------------------------------
all_symbols = mt5.symbols_get()
if all_symbols is None:
    print("Failed to retrieve symbol list.")
    mt5.shutdown()
    sys.exit(1)

candidates = [s.name for s in all_symbols if symbol_input.lower() in s.name.lower()]
if not candidates:
    print(f"No symbol containing '{symbol_input}' found.")
    print("Available symbols (first 20):")
    for i, s in enumerate(all_symbols[:20]):
        print(f"  {s.name}")
    mt5.shutdown()
    sys.exit(1)

exact_match = [s for s in candidates if s.upper() == symbol_input]
if len(exact_match) == 1:
    symbol = exact_match[0]
else:
    print(f"Multiple symbols found containing '{symbol_input}':")
    for i, s in enumerate(candidates):
        print(f"  {i+1}. {s}")
    choice = input("Select number (or press Enter to use the first): ").strip()
    if choice == "":
        symbol = candidates[0]
    else:
        try:
            idx = int(choice) - 1
            symbol = candidates[idx]
        except:
            print("Invalid choice. Exiting.")
            mt5.shutdown()
            sys.exit(1)

print(f"\nUsing symbol: {symbol}")

# Get symbol info
symbol_info = mt5.symbol_info(symbol)
if symbol_info is None:
    print(f"Symbol {symbol} not found.")
    mt5.shutdown()
    sys.exit(1)

print("\n--- Symbol Information ---")
print(f"Name: {symbol_info.name}")
print(f"Description: {symbol_info.description}")
print(f"Trade mode: {symbol_info.trade_mode} (0=disabled, 1=long only, 2=short only, 3=close only, 4=full)")
print(f"Digits: {symbol_info.digits}")
print(f"Contract size: {symbol_info.trade_contract_size}")
print(f"Volume min/max: {symbol_info.volume_min}/{symbol_info.volume_max}")
print(f"Spread: {symbol_info.spread}")
print(f"Tick size: {symbol_info.trade_tick_size}")
print(f"Tick value: {symbol_info.trade_tick_value}")
print(f"Trade allowed: {'Yes' if symbol_info.trade_mode == 4 else 'No'}")

# Ensure symbol is selected in Market Watch
if not symbol_info.visible:
    print(f"Selecting {symbol} in Market Watch...")
    if not mt5.symbol_select(symbol, True):
        print(f"Failed to select {symbol}")
        mt5.shutdown()
        sys.exit(1)
    else:
        # Wait a moment for history to be downloaded (optional)
        time_module.sleep(2)

# ----------------------------------------------------------------------
# Test data availability: try to get just 1 bar
# ----------------------------------------------------------------------
print("\nTesting data availability...")
test_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
if test_rates is None or len(test_rates) == 0:
    print("copy_rates_from_pos(1 bar) failed. Trying copy_rates_from with last hour...")
    now = datetime.now()
    start = now - timedelta(hours=1)
    test_rates = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M1, start, 1)
    if test_rates is None or len(test_rates) == 0:
        print("No 1-minute data available for this symbol.")
        print("Possible reasons:")
        print("- The symbol is not available for your account type (e.g., CFD not enabled).")
        print("- The broker does not provide 1-minute history for this symbol.")
        print("- You may need to open a chart for this symbol in the MT5 terminal first.")
        print("- The symbol might be named differently (e.g., GOLD instead of XAUUSD).")
        mt5.shutdown()
        sys.exit(1)
    else:
        print("Data is available using copy_rates_from with a short range.")
else:
    print("Data is available using copy_rates_from_pos.")

# ----------------------------------------------------------------------
# Fetch historical 1-minute data (now we know it works)
# ----------------------------------------------------------------------
print("Fetching full historical data...")
MAX_BARS = 100000
rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, MAX_BARS)

if rates is None or len(rates) == 0:
    print("copy_rates_from_pos failed for full range. Trying copy_rates_range...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=200)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start_date, end_date)

if rates is None or len(rates) == 0:
    print("Failed to get historical data.")
    print("Last error:", mt5.last_error())
    mt5.shutdown()
    sys.exit(1)

print(f"Downloaded {len(rates)} 1-minute bars.")

# Rest of the script remains the same...
# (convert to bars, group by date, backtest, etc.)
# I'll include the rest for completeness but you can keep your existing code from here onward.
# ----------------------------------------------------------------------
# Convert to list of dictionaries
bars = []
for r in rates:
    bars.append({
        'time': datetime.fromtimestamp(r['time']),
        'open': r['open'],
        'high': r['high'],
        'low': r['low'],
        'close': r['close'],
    })

# Group bars by trading date (filter to only the trading window 09:30-11:30)
bars_by_date = defaultdict(list)
for bar in bars:
    t = bar['time'].time()
    if time(9, 30) <= t < time(11, 30):
        bars_by_date[bar['time'].date()].append(bar)

dates = sorted(bars_by_date.keys())
if len(dates) > days:
    dates = dates[-days:]

print(f"Found {len(dates)} trading days with data in the trading window.")

if len(dates) == 0:
    print("No data in the 09:30-11:30 window. Check your server timezone or the symbol's trading hours.")
    mt5.shutdown()
    sys.exit(1)

# ----------------------------------------------------------------------
# Strategy parameters (fixed)
# ----------------------------------------------------------------------
TP_PCT = 0.005
SL_PCT = 0.0025
contract_size = symbol_info.trade_contract_size
if contract_size == 0:
    print("Contract size is zero, cannot compute profit. Exiting.")
    mt5.shutdown()
    sys.exit(1)

# Helper to compute margin
def compute_margin(order_type, price):
    if order_type == 'buy':
        mt5_order_type = mt5.ORDER_TYPE_BUY
    else:
        mt5_order_type = mt5.ORDER_TYPE_SELL
    margin = mt5.order_calc_margin(mt5_order_type, symbol, lot, price)
    if margin is None:
        print("Margin calculation error:", mt5.last_error())
        return None
    return margin

# Main backtest loop
trades = []
current_balance = balance

for day in dates:
    day_bars = bars_by_date[day]
    if len(day_bars) < 7:
        continue

    orb_bars = day_bars[:6]
    orb_high = max(b['high'] for b in orb_bars)
    orb_low = min(b['low'] for b in orb_bars)

    prev_close = orb_bars[-1]['close']

    trade_active = False
    entry_price = None
    direction = 0
    tp_price = None
    sl_price = None
    exit_price = None
    exit_reason = None

    for i in range(6, len(day_bars)):
        bar = day_bars[i]

        if not trade_active:
            if bar['close'] > orb_high and prev_close <= orb_high:
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

            prev_close = bar['close']

        else:
            if direction == 1:
                if bar['high'] >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    break
                elif bar['low'] <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    break
            else:
                if bar['low'] <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    break
                elif bar['high'] >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    break

    if trade_active and exit_price is None:
        exit_price = day_bars[-1]['close']
        exit_reason = 'EOD'

    if trade_active:
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

# Output results
print("\n" + "="*60)
print(f"Backtest Results for {symbol} ({len(dates)} days, lot={lot})")
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