import MetaTrader5 as mt5
import datetime
import time
import sys
from zoneinfo import ZoneInfo
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import db

NY_TZ = ZoneInfo("America/New_York")
console = Console()

# ─────────────────────────────────────────────
# STRATEGY PARAMETERS (matching indicator & backtest)
# ─────────────────────────────────────────────
RANGE_START = datetime.time(9, 30)
RANGE_END   = datetime.time(9, 36)
TRADE_START = datetime.time(9, 36)
TRADE_END   = datetime.time(11, 30)

TP1_PCT = 0.0025   # 0.25% - first take profit
TP2_PCT = 0.005    # 0.50% - second take profit
SL_PCT  = 0.0025   # 0.25% - stop loss

CONTRACT_SIZE = 100  # XAUUSD = 100 oz per lot

# ─────────────────────────────────────────────
# STATE MACHINE
# ─────────────────────────────────────────────
STATE_IDLE       = "IDLE"
STATE_BUILDING   = "BUILDING"
STATE_WAIT_BREAK = "WAIT_BREAK"
STATE_HALF_OPEN  = "HALF_OPEN"
STATE_TRAIL      = "TRAIL"
STATE_DONE       = "DONE"

STATE_COLORS = {
    STATE_IDLE:       "grey50",
    STATE_BUILDING:   "cyan",
    STATE_WAIT_BREAK: "yellow",
    STATE_HALF_OPEN:  "green",
    STATE_TRAIL:      "bright_green",
    STATE_DONE:       "red",
}

STATE_LABELS = {
    STATE_IDLE:       "IDLE — waiting for range window",
    STATE_BUILDING:   "BUILDING — collecting ORB range",
    STATE_WAIT_BREAK: "WAITING — watching for breakout",
    STATE_HALF_OPEN:  "ACTIVE — TP1 pending",
    STATE_TRAIL:      "TRAILING — SL at break-even, TP2 pending",
    STATE_DONE:       "DONE — day finished",
}


class ORBLiveBot:
    def __init__(self, symbol, lots=0.02):
        self.symbol = symbol
        self.lots = lots
        self.state = STATE_IDLE

        # ORB range
        self.orb_high = None
        self.orb_low = None
        self.range_building = False
        self.range_locked = False

        # Trade
        self.trade_long = False
        self.entry_price = None
        self.tp1_price = None
        self.tp2_price = None
        self.sl_price = None
        self.ticket = None
        self.initial_volume = 0.0
        self.current_volume = 0.0

        # Tracking
        self.tp1_hit = False
        self.tp2_hit = False
        self.day_done = False
        self.current_date = None

        # Timing
        self.last_bar_time = None
        self.tick_count = 0

    def log(self, msg):
        now_ny = datetime.datetime.now(NY_TZ)
        ts = now_ny.strftime("%H:%M:%S.%f")[:-3]
        console.print(f"[dim]{ts}[/dim] {msg}")

    def get_current_time_ny(self):
        return datetime.datetime.now(NY_TZ)

    def get_tick(self):
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None
        return {
            'bid': tick.bid,
            'ask': tick.ask,
            'last': tick.last,
            'time': datetime.datetime.fromtimestamp(tick.time, tz=NY_TZ),
        }

    def get_bar_m1(self):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, 1)
        if rates is None or len(rates) == 0:
            return None
        r = rates[0]
        return {
            'time': datetime.datetime.fromtimestamp(r[0], tz=NY_TZ),
            'open': r[1],
            'high': r[2],
            'low': r[3],
            'close': r[4],
        }

    def get_last_two_bars(self):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, 2)
        if rates is None or len(rates) < 2:
            return None, None
        bars = []
        for r in rates:
            bars.append({
                'time': datetime.datetime.fromtimestamp(r[0], tz=NY_TZ),
                'open': r[1],
                'high': r[2],
                'low': r[3],
                'close': r[4],
            })
        return bars[1], bars[0]  # prev, current

    def check_new_day(self):
        now = self.get_current_time_ny()
        today = now.date()
        if self.current_date != today:
            self.current_date = today
            self.reset_day()
            return True
        return False

    def reset_day(self):
        self.state = STATE_IDLE
        self.orb_high = None
        self.orb_low = None
        self.range_building = False
        self.range_locked = False
        self.trade_long = False
        self.entry_price = None
        self.tp1_price = None
        self.tp2_price = None
        self.sl_price = None
        self.ticket = None
        self.initial_volume = 0.0
        self.current_volume = 0.0
        self.tp1_hit = False
        self.tp2_hit = False
        self.day_done = False
        self.last_bar_time = None
        self.log("[yellow]Day reset — waiting for new session[/yellow]")

    # ─────────────────────────────────────────
    # ORB RANGE BUILDING
    # ─────────────────────────────────────────
    def update_orb_range(self, bar):
        t = bar['time'].time()
        in_range = RANGE_START <= t < RANGE_END

        if in_range and not self.range_locked:
            if self.orb_high is None:
                self.orb_high = bar['high']
                self.orb_low = bar['low']
                self.range_building = True
                self.state = STATE_BUILDING
                self.log(f"[cyan]Range started — High: {self.orb_high:.5f}  Low: {self.orb_low:.5f}[/cyan]")
            else:
                self.orb_high = max(self.orb_high, bar['high'])
                self.orb_low = min(self.orb_low, bar['low'])

        if not in_range and self.range_building and not self.range_locked:
            self.range_locked = True
            self.range_building = False
            self.state = STATE_WAIT_BREAK
            self.log(f"[yellow]Range LOCKED — High: {self.orb_high:.5f}  Low: {self.orb_low:.5f}[/yellow]")
            self.log("[yellow]Waiting for breakout...[/yellow]")

    # ─────────────────────────────────────────
    # BREAKOUT DETECTION
    # ─────────────────────────────────────────
    def check_breakout(self, prev_bar, curr_bar):
        if self.state != STATE_WAIT_BREAK:
            return
        if self.day_done:
            return

        now = self.get_current_time_ny().time()
        if not (TRADE_START <= now < TRADE_END):
            return

        # Bullish breakout: close crosses above orb_high
        if curr_bar['close'] > self.orb_high and prev_bar['close'] <= self.orb_high:
            self.enter_long(curr_bar['close'])

        # Bearish breakout: close crosses below orb_low
        elif curr_bar['close'] < self.orb_low and prev_bar['close'] >= self.orb_low:
            self.enter_short(curr_bar['close'])

    # ─────────────────────────────────────────
    # ENTER TRADE
    # ─────────────────────────────────────────
    def enter_long(self, price):
        self.trade_long = True
        self.entry_price = price
        self.tp1_price = self.entry_price * (1 + TP1_PCT)
        self.tp2_price = self.entry_price * (1 + TP2_PCT)
        self.sl_price  = self.entry_price * (1 - SL_PCT)
        self.initial_volume = self.lots
        self.current_volume = self.lots
        self.tp1_hit = False
        self.tp2_hit = False

        self.log(f"[green]LONG ENTRY @ {self.entry_price:.5f}[/green]")
        self.log(f"  TP1: {self.tp1_price:.5f}  TP2: {self.tp2_price:.5f}  SL: {self.sl_price:.5f}")

        self.send_order(mt5.ORDER_TYPE_BUY, self.lots)

        db.log_event("ENTRY_LONG", {
            "direction": "LONG",
            "entry": f"{self.entry_price:.5f}",
            "tp1": f"{self.tp1_price:.5f}",
            "tp2": f"{self.tp2_price:.5f}",
            "sl": f"{self.sl_price:.5f}",
            "volume": self.lots,
            "orb_high": f"{self.orb_high:.5f}" if self.orb_high else "",
            "orb_low": f"{self.orb_low:.5f}" if self.orb_low else "",
            "comment": "OR open",
        })

    def enter_short(self, price):
        self.trade_long = False
        self.entry_price = price
        self.tp1_price = self.entry_price * (1 - TP1_PCT)
        self.tp2_price = self.entry_price * (1 - TP2_PCT)
        self.sl_price  = self.entry_price * (1 + SL_PCT)
        self.initial_volume = self.lots
        self.current_volume = self.lots
        self.tp1_hit = False
        self.tp2_hit = False

        self.log(f"[red]SHORT ENTRY @ {self.entry_price:.5f}[/red]")
        self.log(f"  TP1: {self.tp1_price:.5f}  TP2: {self.tp2_price:.5f}  SL: {self.sl_price:.5f}")

        self.send_order(mt5.ORDER_TYPE_SELL, self.lots)

        db.log_event("ENTRY_SHORT", {
            "direction": "SHORT",
            "entry": f"{self.entry_price:.5f}",
            "tp1": f"{self.tp1_price:.5f}",
            "tp2": f"{self.tp2_price:.5f}",
            "sl": f"{self.sl_price:.5f}",
            "volume": self.lots,
            "orb_high": f"{self.orb_high:.5f}" if self.orb_high else "",
            "orb_low": f"{self.orb_low:.5f}" if self.orb_low else "",
            "comment": "OR open",
        })

    # ─────────────────────────────────────────
    # SEND ORDER TO MT5
    # ─────────────────────────────────────────
    def send_order(self, order_type, volume):
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            self.log(f"[red]ERROR: Cannot get symbol info for {self.symbol}[/red]")
            return False

        if not symbol_info.visible:
            mt5.symbol_select(self.symbol, True)

        price = symbol_info.ask if order_type == mt5.ORDER_TYPE_BUY else symbol_info.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 30,
            "magic": 202609,
            "comment": "ORB_LIVE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            self.log(f"[red]ERROR: order_send returned None — {mt5.last_error()}[/red]")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log(f"[red]ERROR: Order failed — {result.comment} (code {result.retcode})[/red]")
            return False

        self.ticket = result.order
        self.log(f"[green]Order FILLED — Ticket: {self.ticket}  Volume: {volume}  Price: {result.price:.5f}[/green]")
        self.state = STATE_HALF_OPEN
        return True

    # ─────────────────────────────────────────
    # CLOSE POSITION (partial or full)
    # ─────────────────────────────────────────
    def close_position(self, volume=None):
        if self.ticket is None:
            self.log("[red]ERROR: No ticket to close[/red]")
            return False

        positions = mt5.positions_get(ticket=self.ticket)
        if positions is None or len(positions) == 0:
            self.log(f"[yellow]WARNING: Position {self.ticket} not found — may already be closed[/yellow]")
            self.ticket = None
            self.day_done = True
            self.state = STATE_DONE
            return True

        pos = positions[0]
        close_vol = volume if volume else pos.volume
        close_vol = round(close_vol, 2)

        if close_vol <= 0:
            self.log("[yellow]WARNING: Volume to close is 0[/yellow]")
            return False

        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            self.log(f"[red]ERROR: Cannot get symbol info for {self.symbol}[/red]")
            return False

        # Opposite type to close
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        if pos.type == mt5.ORDER_TYPE_BUY:
            close_price = symbol_info.bid
        else:
            close_price = symbol_info.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": close_vol,
            "type": close_type,
            "position": self.ticket,
            "price": close_price,
            "deviation": 30,
            "magic": 202609,
            "comment": "ORB_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else str(mt5.last_error())
            self.log(f"[red]ERROR: Close failed — {err}[/red]")
            return False

        self.current_volume = round(self.current_volume - close_vol, 2)
        self.log(f"[bright_blue]CLOSED {close_vol} lots @ {result.price:.5f}  Remaining: {self.current_volume}[/bright_blue]")
        return True

    # ─────────────────────────────────────────
    # MODIFY SL
    # ─────────────────────────────────────────
    def modify_sl(self, new_sl):
        if self.ticket is None:
            return False

        positions = mt5.positions_get(ticket=self.ticket)
        if positions is None or len(positions) == 0:
            return False

        pos = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": self.ticket,
            "sl": new_sl,
            "tp": 0,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else str(mt5.last_error())
            self.log(f"[red]ERROR: SL modify failed — {err}[/red]")
            return False

        self.sl_price = new_sl
        self.log(f"[bright_cyan]SL MOVED to {new_sl:.5f}[/bright_cyan]")
        return True

    # ─────────────────────────────────────────
    # MANAGE TRADE ON EACH TICK
    # ─────────────────────────────────────────
    def manage_trade(self, tick):
        if self.state not in (STATE_HALF_OPEN, STATE_TRAIL):
            return

        if self.ticket is None:
            return

        price = tick['bid'] if self.trade_long else tick['ask']
        self.tick_count += 1

        # Check TP1: close 50%, move SL to break-even
        if not self.tp1_hit:
            if self.trade_long and tick['ask'] >= self.tp1_price:
                self.tp1_hit = True
                self.log(f"[green]TP1 HIT @ {tick['ask']:.5f}[/green]")
                half_vol = round(self.initial_volume / 2, 2)
                if self.close_position(half_vol):
                    self.modify_sl(self.entry_price)
                    self.state = STATE_TRAIL
                    self.log("[green]SL moved to break-even (entry price)[/green]")
                    db.log_event("TP1_HIT", {
                        "direction": "LONG",
                        "entry": f"{self.entry_price:.5f}",
                        "close_price": f"{tick['ask']:.5f}",
                        "volume": half_vol,
                        "pnl": round((tick['ask'] - self.entry_price) * half_vol * CONTRACT_SIZE, 2),
                        "comment": "TP1 — close 50%, SL to BE",
                    })

            elif not self.trade_long and tick['bid'] <= self.tp1_price:
                self.tp1_hit = True
                self.log(f"[green]TP1 HIT @ {tick['bid']:.5f}[/green]")
                half_vol = round(self.initial_volume / 2, 2)
                if self.close_position(half_vol):
                    self.modify_sl(self.entry_price)
                    self.state = STATE_TRAIL
                    self.log("[green]SL moved to break-even (entry price)[/green]")
                    db.log_event("TP1_HIT", {
                        "direction": "SHORT",
                        "entry": f"{self.entry_price:.5f}",
                        "close_price": f"{tick['bid']:.5f}",
                        "volume": half_vol,
                        "pnl": round((self.entry_price - tick['bid']) * half_vol * CONTRACT_SIZE, 2),
                        "comment": "TP1 — close 50%, SL to BE",
                    })

        # Check TP2: close remaining
        if self.tp1_hit and not self.tp2_hit:
            if self.trade_long and tick['ask'] >= self.tp2_price:
                self.tp2_hit = True
                self.log(f"[bright_green]TP2 HIT @ {tick['ask']:.5f}[/bright_green]")
                self.close_position()
                self.day_done = True
                self.state = STATE_DONE
                self.log("[bright_green]ALL POSITIONS CLOSED — Day done[/bright_green]")
                db.log_event("TP2_HIT", {
                    "direction": "LONG",
                    "entry": f"{self.entry_price:.5f}",
                    "close_price": f"{tick['ask']:.5f}",
                    "volume": self.current_volume,
                    "pnl": round((tick['ask'] - self.entry_price) * self.current_volume * CONTRACT_SIZE, 2),
                    "comment": "TP2 — full close",
                })

            elif not self.trade_long and tick['bid'] <= self.tp2_price:
                self.tp2_hit = True
                self.log(f"[bright_green]TP2 HIT @ {tick['bid']:.5f}[/bright_green]")
                self.close_position()
                self.day_done = True
                self.state = STATE_DONE
                self.log("[bright_green]ALL POSITIONS CLOSED — Day done[/bright_green]")
                db.log_event("TP2_HIT", {
                    "direction": "SHORT",
                    "entry": f"{self.entry_price:.5f}",
                    "close_price": f"{tick['bid']:.5f}",
                    "volume": self.current_volume,
                    "pnl": round((self.entry_price - tick['bid']) * self.current_volume * CONTRACT_SIZE, 2),
                    "comment": "TP2 — full close",
                })

        # Check SL
        if self.trade_long and tick['bid'] <= self.sl_price:
            self.log(f"[red]SL HIT @ {tick['bid']:.5f}[/red]")
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("[red]STOPPED OUT — Day done[/red]")
            db.log_event("SL_HIT", {
                "direction": "LONG",
                "entry": f"{self.entry_price:.5f}",
                "close_price": f"{tick['bid']:.5f}",
                "volume": self.current_volume,
                "pnl": round((tick['bid'] - self.entry_price) * self.current_volume * CONTRACT_SIZE, 2),
                "comment": "SL hit",
            })

        elif not self.trade_long and tick['ask'] >= self.sl_price:
            self.log(f"[red]SL HIT @ {tick['ask']:.5f}[/red]")
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("[red]STOPPED OUT — Day done[/red]")
            db.log_event("SL_HIT", {
                "direction": "SHORT",
                "entry": f"{self.entry_price:.5f}",
                "close_price": f"{tick['ask']:.5f}",
                "volume": self.current_volume,
                "pnl": round((self.entry_price - tick['ask']) * self.current_volume * CONTRACT_SIZE, 2),
                "comment": "SL hit",
            })

    # ─────────────────────────────────────────
    # FORCE CLOSE AT 11:30
    # ─────────────────────────────────────────
    def check_force_close(self):
        now = self.get_current_time_ny().time()
        if now >= TRADE_END and self.state in (STATE_HALF_OPEN, STATE_TRAIL):
            self.log("[red]11:30 NY — FORCE CLOSE[/red]")
            close_price = self.get_tick()
            cp = close_price['bid'] if self.trade_long else close_price['ask'] if close_price else self.entry_price
            pnl_dir = (cp - self.entry_price) if self.trade_long else (self.entry_price - cp)
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("[red]Day done — force closed[/red]")
            db.log_event("FORCE_CLOSE", {
                "direction": "LONG" if self.trade_long else "SHORT",
                "entry": f"{self.entry_price:.5f}",
                "close_price": f"{cp:.5f}",
                "volume": self.current_volume,
                "pnl": round(pnl_dir * self.current_volume * CONTRACT_SIZE, 2),
                "comment": "11:30 NY force close",
            })

    # ─────────────────────────────────────────
    # EMERGENCY STOP
    # ─────────────────────────────────────────
    def emergency_stop(self):
        self.log("[red bold]EMERGENCY STOP — Closing all positions...[/red bold]")
        positions = mt5.positions_get(symbol=self.symbol)
        if positions:
            for pos in positions:
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                symbol_info = mt5.symbol_info(self.symbol)
                close_price = symbol_info.bid if pos.type == mt5.ORDER_TYPE_BUY else symbol_info.ask

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": close_price,
                    "deviation": 30,
                    "magic": 202609,
                    "comment": "ORB_EMERGENCY",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.log(f"[green]Emergency closed {pos.volume} lots @ {result.price:.5f}[/green]")
                    direction = "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT"
                    entry_val = self.entry_price if self.entry_price else 0
                    pnl_dir = (result.price - entry_val) if pos.type == mt5.ORDER_TYPE_BUY else (entry_val - result.price)
                    db.log_event("EMERGENCY_CLOSE", {
                        "direction": direction,
                        "entry": f"{entry_val:.5f}",
                        "close_price": f"{result.price:.5f}",
                        "volume": pos.volume,
                        "pnl": round(pnl_dir * pos.volume * CONTRACT_SIZE, 2),
                        "comment": "Emergency Ctrl+C close",
                    })
                else:
                    self.log(f"[red]Emergency close FAILED for ticket {pos.ticket}[/red]")
        else:
            self.log("[yellow]No open positions to close[/yellow]")

    # ─────────────────────────────────────────
    # RICH PANEL DISPLAY
    # ─────────────────────────────────────────
    def build_panel(self) -> Panel:
        now = self.get_current_time_ny()
        price = self.get_tick()
        bid = price['bid'] if price else 0
        ask = price['ask'] if price else 0

        # Header
        header = Text()
        header.append(f" {self.symbol}  ", style="bold white on blue")
        header.append(f"  {now.strftime('%Y-%m-%d %H:%M:%S')} NY", style="bold")

        # State badge
        state_color = STATE_COLORS.get(self.state, "white")
        state_label = STATE_LABELS.get(self.state, self.state)
        state_line = Text()
        state_line.append("  State:  ")
        state_line.append(f" {state_label} ", style=f"bold {state_color} on {state_color} reverse")

        # Price
        price_line = Text()
        price_line.append("  Bid: ")
        price_line.append(f"{bid:.5f}", style="green" if bid else "grey50")
        price_line.append("  Ask: ")
        price_line.append(f"{ask:.5f}", style="red" if ask else "grey50")

        # ORB range
        if self.orb_high and self.orb_low:
            orb_line = Text()
            orb_line.append("  ORB:  ")
            orb_line.append(f"{self.orb_high:.5f}", style="cyan")
            orb_line.append(" / ")
            orb_line.append(f"{self.orb_low:.5f}", style="red")
            spread = self.orb_high - self.orb_low
            orb_line.append(f"  ({spread:.5f})", style="dim")
        else:
            orb_line = Text("  ORB:  Building...", style="dim")

        # Build layout
        lines = [header, state_line, price_line, orb_line]

        # Position info
        if self.state in (STATE_HALF_OPEN, STATE_TRAIL):
            direction = "LONG" if self.trade_long else "SHORT"
            dir_color = "green" if self.trade_long else "red"

            lines.append(Text(""))

            pos_line = Text()
            pos_line.append("  Pos:   ")
            pos_line.append(f"{direction}", style=f"bold {dir_color}")
            pos_line.append("  Entry: ")
            pos_line.append(f"{self.entry_price:.5f}", style="yellow")

            vol_line = Text()
            vol_line.append("  Vol:   ")
            vol_line.append(f"{self.current_volume:.2f}", style="white")
            vol_line.append(f" / {self.initial_volume:.2f}", style="dim")

            tp1_status = "[green]HIT[/green]" if self.tp1_hit else "[dim]pending[/dim]"
            tp2_status = "[green]HIT[/green]" if self.tp2_hit else "[dim]pending[/dim]"

            tp1_line = Text()
            tp1_line.append("  TP1:  ")
            tp1_line.append(f"{self.tp1_price:.5f}", style="green")
            tp1_line.append(f"  ({tp1_status})", style="dim" if not self.tp1_hit else "green")

            tp2_line = Text()
            tp2_line.append("  TP2:  ")
            tp2_line.append(f"{self.tp2_price:.5f}", style="green")
            tp2_line.append(f"  ({tp2_status})", style="dim" if not self.tp2_hit else "green")

            sl_line = Text()
            sl_line.append("  SL:   ")
            sl_line.append(f"{self.sl_price:.5f}", style="red")

            lines.extend([pos_line, vol_line, tp1_line, tp2_line, sl_line])

        # Footer
        lines.append(Text(""))
        footer = Text("  Ctrl+C to emergency stop", style="dim italic")
        lines.append(footer)

        # Compose panel content
        content = Text("\n").join(lines)

        # Panel title
        state_color = STATE_COLORS.get(self.state, "white")
        title = Text(f" ORB BOT ", style=f"bold white on {state_color}")
        border_color = state_color

        return Panel(
            content,
            title=title,
            border_style=border_color,
            padding=(0, 1),
        )


def main():
    # Startup banner
    banner = Panel(
        Text(
            "  ORB LIVE TRADING BOT — MetaTrader 5\n"
            "  Opening Range Breakout · New York Session\n"
            "  Range: 09:30–09:36  Trade: 09:36–11:30\n"
            "  TP1: +0.25%  TP2: +0.50%  SL: -0.25%",
            justify="center"
        ),
        title="[bold blue]ORB BOT[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    )
    console.print(banner)
    console.print()

    if not mt5.initialize():
        console.print(f"[red]MT5 initialization failed: {mt5.last_error()}[/red]")
        sys.exit(1)

    console.print("[green]MT5 initialized successfully.[/green]\n")

    account_info = mt5.account_info()
    if account_info:
        acct_table = Table(show_header=False, box=None, padding=(0, 2))
        acct_table.add_column("Key", style="dim")
        acct_table.add_column("Value", style="bold")
        acct_table.add_row("Account", str(account_info.login))
        acct_table.add_row("Server", account_info.server)
        acct_table.add_row("Balance", f"${account_info.balance:,.2f}")
        acct_table.add_row("Free", f"${account_info.margin_free:,.2f}")
        console.print(acct_table)
        console.print()

    symbol = input("Enter symbol (e.g. XAUUSD): ").strip().upper()
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        console.print(f"[red]Symbol '{symbol}' not found. Available symbols:[/red]")
        symbols = mt5.symbols_get()
        for s in symbols[:20]:
            console.print(f"  {s.name}")
        mt5.shutdown()
        sys.exit(1)

    mt5.symbol_select(symbol, True)

    lots_str = input("Enter lot size (e.g. 0.02): ").strip()
    lots = float(lots_str)

    console.print()
    console.print(Panel(
        f"  Symbol: [bold]{symbol}[/bold]  |  Lots: [bold]{lots}[/bold]\n"
        f"  Range:  {RANGE_START} — {RANGE_END} NY\n"
        f"  Trade:  {TRADE_START} — {TRADE_END} NY\n"
        f"  TP1: +0.25%  TP2: +0.50%  SL: -0.25%",
        title="[bold]Config[/bold]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()

    bot = ORBLiveBot(symbol, lots)

    # Check if we're in range building or trading time
    now_ny = bot.get_current_time_ny()
    today = now_ny.date()
    bot.current_date = today

    # Load today's existing M1 bars if any
    today_start = datetime.datetime(today.year, today.month, today.day, tzinfo=NY_TZ)
    today_start_utc = today_start.astimezone(datetime.timezone.utc)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, today_start_utc, now_ny.astimezone(datetime.timezone.utc))

    if rates is not None and len(rates) > 0:
        console.print(f"  Found {len(rates)} existing M1 bars for today")
        for r in rates:
            bar = {
                'time': datetime.datetime.fromtimestamp(r[0], tz=NY_TZ),
                'open': r[1],
                'high': r[2],
                'low': r[3],
                'close': r[4],
            }
            bot.update_orb_range(bar)
            bot.last_bar_time = bar['time']

        if bot.range_locked:
            console.print(f"  ORB range already built: {bot.orb_high:.5f} / {bot.orb_low:.5f}")

    console.print("\n[bold green]Bot is running. Monitoring ticks...[/bold green]\n")

    try:
        with Live(bot.build_panel(), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                now_ny = bot.get_current_time_ny()

                # Check for new day
                bot.check_new_day()

                # Force close at 11:30
                bot.check_force_close()

                # Get current tick (real-time, millisecond updates)
                tick = bot.get_tick()
                if tick is None:
                    time.sleep(0.1)
                    continue

                # Check if new M1 bar arrived
                curr_bar = bot.get_bar_m1()
                if curr_bar is not None:
                    if bot.last_bar_time is None or curr_bar['time'] != bot.last_bar_time:
                        bot.last_bar_time = curr_bar['time']

                        # Update ORB range with new bar
                        bot.update_orb_range(curr_bar)

                        # Check breakout on new bar
                        prev_bar, curr_bar = bot.get_last_two_bars()
                        if prev_bar and curr_bar:
                            bot.check_breakout(prev_bar, curr_bar)

                # Manage active trade on every tick (millisecond updates)
                bot.manage_trade(tick)

                # Update panel in-place
                live.update(bot.build_panel())

                # Sleep 100ms for tick updates
                time.sleep(0.1)

    except KeyboardInterrupt:
        console.print("\n\n[bold red]Ctrl+C detected — emergency stop...[/bold red]")
        bot.emergency_stop()
        console.print(bot.build_panel())
    finally:
        db.generate_all_html()
        console.print("\n[green]Exported all.html[/green]")
        mt5.shutdown()
        console.print("[green]MT5 shutdown complete.[/green]")


if __name__ == '__main__':
    main()
