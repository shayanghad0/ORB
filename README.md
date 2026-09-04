# ORB - Opening Range Breakout

Python implementation of the ORB (Opening Range Breakout) trading strategy for XAUUSD, with both **backtesting** and **live trading** via MetaTrader 5.

## Files

| File | Description |
|------|-------------|
| `orb_strategy.py` | Backtest engine — reads M1 JSON data, detects ORB trades, calculates margin/P&L, outputs HTML report with charts |
| `orb_live.py` | Live trading bot — connects to MT5, builds ORB range in real-time, executes trades with partial TP + trailing SL |
| `ORB_Live.mq5` | MQL5 Expert Advisor — native MT5 EA, same logic as orb_live.py, runs directly in MetaTrader 5 |
| `db.py` | Trade logging — persists every trade event to JSON, auto-generates HTML reports |
| `indicator/v5.pine` | Pine Script v5 indicator |
| `indicator/v6.pine` | Pine Script v6 indicator (partial close) |

## Backtest (`orb_strategy.py`)

### How to Run

```bash
cd C:\Users\Shayan\Desktop\ORB\JSON
python orb_strategy.py
```

### Inputs

- **Account Balance** — starting balance in USD (e.g. `100`)
- **Leverage** — broker leverage (e.g. `500` for 1:500)

### How It Works

1. Scans current directory for `*_M1.json` files (1-minute OHLC data)
2. For each day, builds ORB range from bars `09:31–09:36` (New York time)
3. Detects breakout when price crosses ORB High (LONG) or ORB Low (SHORT)
4. Calculates lot size, margin, free margin, and P&L per trade
5. Generates:
   - Individual `*_ORB.json` files per day
   - `*_ORB.png` candlestick charts with ORB levels
   - `orb_results.html` — full report with account summary and charts

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Range Session | 09:31–09:36 NY | 6 M1 bars form the opening range |
| Trade Session | 09:30–11:30 NY | Window to detect breakouts |
| Take Profit | 0.5% | Full TP target |
| Stop Loss | 0.25% | Initial SL from entry |
| Lot Size | Auto | Calculated from balance & leverage (2% risk) |

### Margin Formula

```
Margin = (Lots × Contract Size × Price) / Leverage
Contract Size = 100 oz (XAUUSD)
```

### Example Output

```
+----------------------------------+
|       ORB BACKTEST - SETUP       |
+----------------------------------+
Enter account balance (e.g. 1000): 100
Enter leverage (e.g. 500 for 1:500): 500

Balance: $100.00  |  Leverage: 1:500
  Lot size: 0.01  Margin: $8.32  P&L: +20.80  Balance: $120.80
```

## Live Bot (`orb_live.py`)

### Requirements

- MetaTrader 5 installed and logged into your broker account
- Python package: `pip install MetaTrader5`

### How to Run

1. Open MetaTrader 5 and log into your account
2. Run the bot:

```bash
cd C:\Users\Shayan\Desktop\ORB
python orb_live.py
```

3. Enter your symbol when prompted (e.g. `XAUUSD`)

### Trade Management

| Stage | Action |
|-------|--------|
| 09:31–09:36 | Build ORB range from live M1 data |
| 09:36 | Range locked, wait for breakout |
| Breakout | Open 0.02 lot market order |
| +0.25% (half TP) | Close 0.01 lot (50%), move SL to +0.125% |
| +0.5% (full TP) | Close remaining 0.01 lot |
| 11:30 NY | Force close any open position |
| Ctrl+C | Emergency stop — auto-closes positions |

### State Machine

```
IDLE → BUILDING → WAIT_BREAK → HALF_OPEN → TRAIL → (closed)
```

## MQL5 Expert Advisor (`ORB_Live.mq5`)

Native MQL5 EA with the same logic as `orb_live.py`. Runs directly inside MetaTrader 5 — no Python needed.

### How to Install

1. Copy `ORB_Live.mq5` to `MQL5/Experts/` in your MT5 data folder
2. Open MetaEditor and compile (or press F7)
3. Drag the EA onto a XAUUSD M1 chart
4. Enable "Allow Algo Trading"

### How It Works

Same state machine as the Python bot:

```
IDLE → BUILDING → WAIT_BREAK → HALF_OPEN → TRAIL → DONE
```

- Builds ORB range from M1 bars during the range window
- Detects breakout on bar close (cross above high = LONG, cross below low = SL)
- TP1 (+0.25%): closes 50%, moves SL to break-even
- TP2 (+0.50%): closes remaining
- SL (-0.25%): closes all
- Force close at 11:30 NY
- Press ESC for emergency stop

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Range Start | 09:30 NY | Start of ORB range window |
| Range End | 09:36 NY | End of ORB range window |
| Trade Start | 09:30 NY | Start of trading window |
| Trade End | 11:30 NY | End of trading window (force close) |
| TP1 % | 0.25% | First take profit (close 50%) |
| TP2 % | 0.50% | Second take profit (close rest) |
| SL % | 0.25% | Stop loss |
| Lots | 0.02 | Lot size |
| Magic | 202609 | EA identifier |

### Python vs MQL5

| Feature | `orb_live.py` | `ORB_Live.mq5` |
|---------|---------------|-----------------|
| Requires Python | Yes | No |
| Runs outside MT5 | Yes | No (native) |
| Trade logging | JSON + HTML | Print log only |
| Same strategy | Yes | Yes |
| Same parameters | Yes | Yes |

## Trade Logging (`db.py`)

Every trade event is automatically logged to JSON and HTML reports are generated.

### File Structure

```
ORB/
  all.json              ← master log of all trades
  all.html              ← all trades report (HTML)
  db/
    2026-09-04/
      db.json           ← today's trade log
      index.html        ← today's HTML report
    2026-09-05/
      db.json
      index.html
    ...
```

### What Gets Logged

| Event | Fields |
|-------|--------|
| `ENTRY_LONG` / `ENTRY_SHORT` | direction, entry, tp1, tp2, sl, volume, orb_high, orb_low |
| `TP1_HIT` | direction, entry, close_price, volume, pnl |
| `TP2_HIT` | direction, entry, close_price, volume, pnl |
| `SL_HIT` | direction, entry, close_price, volume, pnl |
| `FORCE_CLOSE` | direction, entry, close_price, volume, pnl (at 11:30 NY) |
| `EMERGENCY_CLOSE` | direction, entry, close_price, volume, pnl (on Ctrl+C) |

### HTML Reports

- **Daily**: `db/{date}/index.html` — auto-generated after each event
- **All Days**: `all.html` — regenerated after each event and exported on Ctrl+C
- Dark theme, summary cards (Total, Long, Short, Wins, Losses, PnL), trade table with color-coded rows

### Ctrl+C Behavior

1. Emergency stop — closes all open positions
2. Generates `all.html` from `all.json`
3. Shuts down MT5

## Data Format

M1 JSON files should be named: `{SYMBOL}_{YYYY-MM-DD}_M1.json`

```json
[
  {
    "time": "2026-09-02T00:00:00-04:00",
    "open": 4300.50,
    "high": 4301.20,
    "low": 4300.10,
    "close": 4300.80
  }
]
```

## Pine Script Reference

The strategy replicates `indicator/v5.pine` with:

- `rangeSessionS = "0930-0936"` → Python uses 09:31–09:36 (Pine excludes bar at session start)
- `tradeSessionS = "0930-1130"`
- `tpPerc = 0.5`, `slPerc = 0.25`

## Disclaimer

This is for educational purposes only. Trading involves risk. Always test on a demo account first.
