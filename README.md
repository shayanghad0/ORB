# ORB - Opening Range Breakout

Python implementation of the ORB (Opening Range Breakout) trading strategy for XAUUSD, with both **backtesting** and **live trading** via MetaTrader 5.

## Files

| File | Description |
|------|-------------|
| `orb_strategy.py` | Backtest engine — reads M1 JSON data, detects ORB trades, calculates margin/P&L, outputs HTML report with charts |
| `orb_live.py` | Live trading bot — connects to MT5, builds ORB range in real-time, executes trades with partial TP + trailing SL |
| `indicator/v5.pine` | Original Pine Script indicator |

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
