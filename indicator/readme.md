# ORB - Opening Range Breakout Indicator

Pine Script v5 indicator for TradingView. Automatically detects the opening range and trades breakouts with partial close and trailing SL.

## How It Works

1. **Range Building** — Collects high/low during the opening range window (default 09:30–09:36)
2. **Breakout Detection** — Signals LONG when price closes above range high, SHORT when below range low
3. **Trade Management** — Sets TP and SL automatically
4. **Partial Close** — Closes 50% of position when 50% of TP is reached, moves SL to breakeven + buffer

## Settings

### Strategy

| Setting | Default | Description |
|---------|---------|-------------|
| Opening Range Window | 0930–0936 | Time window to build the range |
| Trading Window | 0930–1130 | Window where breakout signals are valid |
| TP % | 0.5% | Take profit target |
| SL % | 0.25% | Stop loss distance |
| Partial Close at % of TP | 50% | Close half position at this % of TP |
| SL after partial close | 12.5% | Move SL to this % above/below entry after partial close |

### Display

| Setting | Default | Description |
|---------|---------|-------------|
| Show Opening Range Box | On | Draw the range box on chart |
| Show Entry/TP/SL labels | On | Show price labels |
| Show Breakout Signal Arrow | On | Show arrow on breakout bar |
| Show background highlight | On | Color background during active trades |
| Label offset | 40 bars | Distance of labels from signal |
| Line length | 500 bars | How far lines extend right |

### Colors

| Setting | Default |
|---------|---------|
| Bullish color | Lime |
| Bearish color | Red |
| Entry color | Yellow |
| TP color | Lime |
| SL color | Red |

## Partial Close Logic

Example for a LONG trade:

- Entry: 1000
- TP: 1500 (+0.5%)
- SL: 997.5 (-0.25%)

When price reaches **1250** (50% of TP):

- 50% of position is marked as closed
- SL moves from 997.5 to **1125** (entry + 12.5%)
- Orange label appears: "50% CLOSE"
- Remaining position continues to full TP

For SHORT trades the logic is mirrored.

## Dashboard

Top-right corner table shows:

- Current range values and bar count
- Trade status (Building / Watching / LONG / SHORT / Done)
- Entry price
- TP and SL levels (updates when partial close triggers)
- Risk/Reward ratio

## Reset

All state resets at the start of each new trading session. One trade per day maximum.

## Installation

1. Open TradingView
2. Go to Pine Script editor
3. Paste the code from `v5.pine`
4. Click "Add to Chart"
5. Adjust settings in the indicator settings panel

## License

Mozilla Public License 2.0
