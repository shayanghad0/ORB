import MetaTrader5 as mt5
import datetime
import time
import sys
from zoneinfo import ZoneInfo
import db

NY_TZ = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────
# STRATEGY PARAMETERS (matching indicator & backtest)
# ─────────────────────────────────────────────
RANGE_START = datetime.time(9, 30)
RANGE_END   = datetime.time(9, 36)
TRADE_START = datetime.time(9, 30)
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
        print(f"[{ts}] {msg}")

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
        self.log("Day reset — waiting for new session")

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
                self.log(f"Range started — High: {self.orb_high:.5f}  Low: {self.orb_low:.5f}")
            else:
                self.orb_high = max(self.orb_high, bar['high'])
                self.orb_low = min(self.orb_low, bar['low'])

        if not in_range and self.range_building and not self.range_locked:
            self.range_locked = True
            self.range_building = False
            self.state = STATE_WAIT_BREAK
            self.log(f"Range LOCKED — High: {self.orb_high:.5f}  Low: {self.orb_low:.5f}")
            self.log("Waiting for breakout...")

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

        self.log(f"LONG ENTRY @ {self.entry_price:.5f}")
        self.log(f"  TP1: {self.tp1_price:.5f} (+0.25%)  TP2: {self.tp2_price:.5f} (+0.50%)  SL: {self.sl_price:.5f} (-0.25%)")

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

        self.log(f"SHORT ENTRY @ {self.entry_price:.5f}")
        self.log(f"  TP1: {self.tp1_price:.5f} (-0.25%)  TP2: {self.tp2_price:.5f} (-0.50%)  SL: {self.sl_price:.5f} (+0.25%)")

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
            self.log(f"ERROR: Cannot get symbol info for {self.symbol}")
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
            self.log(f"ERROR: order_send returned None — {mt5.last_error()}")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log(f"ERROR: Order failed — {result.comment} (code {result.retcode})")
            return False

        self.ticket = result.order
        self.log(f"Order FILLED — Ticket: {self.ticket}  Volume: {volume}  Price: {result.price:.5f}")
        self.state = STATE_HALF_OPEN
        return True

    # ─────────────────────────────────────────
    # CLOSE POSITION (partial or full)
    # ─────────────────────────────────────────
    def close_position(self, volume=None):
        if self.ticket is None:
            self.log("ERROR: No ticket to close")
            return False

        positions = mt5.positions_get(ticket=self.ticket)
        if positions is None or len(positions) == 0:
            self.log(f"WARNING: Position {self.ticket} not found — may already be closed")
            self.ticket = None
            self.day_done = True
            self.state = STATE_DONE
            return True

        pos = positions[0]
        close_vol = volume if volume else pos.volume
        close_vol = round(close_vol, 2)

        if close_vol <= 0:
            self.log("WARNING: Volume to close is 0")
            return False

        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            self.log(f"ERROR: Cannot get symbol info for {self.symbol}")
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
            self.log(f"ERROR: Close failed — {err}")
            return False

        self.current_volume = round(self.current_volume - close_vol, 2)
        self.log(f"CLOSED {close_vol} lots @ {result.price:.5f}  Remaining: {self.current_volume}")
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
            self.log(f"ERROR: SL modify failed — {err}")
            return False

        self.sl_price = new_sl
        self.log(f"SL MOVED to {new_sl:.5f}")
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
                self.log(f"TP1 HIT @ {tick['ask']:.5f}")
                half_vol = round(self.initial_volume / 2, 2)
                if self.close_position(half_vol):
                    self.modify_sl(self.entry_price)
                    self.state = STATE_TRAIL
                    self.log("SL moved to break-even (entry price)")
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
                self.log(f"TP1 HIT @ {tick['bid']:.5f}")
                half_vol = round(self.initial_volume / 2, 2)
                if self.close_position(half_vol):
                    self.modify_sl(self.entry_price)
                    self.state = STATE_TRAIL
                    self.log("SL moved to break-even (entry price)")
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
                self.log(f"TP2 HIT @ {tick['ask']:.5f}")
                self.close_position()
                self.day_done = True
                self.state = STATE_DONE
                self.log("ALL POSITIONS CLOSED — Day done")
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
                self.log(f"TP2 HIT @ {tick['bid']:.5f}")
                self.close_position()
                self.day_done = True
                self.state = STATE_DONE
                self.log("ALL POSITIONS CLOSED — Day done")
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
            self.log(f"SL HIT @ {tick['bid']:.5f}")
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("STOPPED OUT — Day done")
            db.log_event("SL_HIT", {
                "direction": "LONG",
                "entry": f"{self.entry_price:.5f}",
                "close_price": f"{tick['bid']:.5f}",
                "volume": self.current_volume,
                "pnl": round((tick['bid'] - self.entry_price) * self.current_volume * CONTRACT_SIZE, 2),
                "comment": "SL hit",
            })

        elif not self.trade_long and tick['ask'] >= self.sl_price:
            self.log(f"SL HIT @ {tick['ask']:.5f}")
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("STOPPED OUT — Day done")
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
            self.log("11:30 NY — FORCE CLOSE")
            close_price = self.get_tick()
            cp = close_price['bid'] if self.trade_long else close_price['ask'] if close_price else self.entry_price
            pnl_dir = (cp - self.entry_price) if self.trade_long else (self.entry_price - cp)
            self.close_position()
            self.day_done = True
            self.state = STATE_DONE
            self.log("Day done — force closed")
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
        self.log("EMERGENCY STOP — Closing all positions...")
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
                    self.log(f"Emergency closed {pos.volume} lots @ {result.price:.5f}")
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
                    self.log(f"Emergency close FAILED for ticket {pos.ticket}")
        else:
            self.log("No open positions to close")

    # ─────────────────────────────────────────
    # STATUS DISPLAY
    # ─────────────────────────────────────────
    def print_status(self):
        now = self.get_current_time_ny()
        price = self.get_tick()
        bid = price['bid'] if price else 0
        ask = price['ask'] if price else 0

        status = {
            STATE_IDLE: "IDLE — waiting for range window",
            STATE_BUILDING: "BUILDING — collecting ORB range",
            STATE_WAIT_BREAK: "WAITING — range locked, watching for breakout",
            STATE_HALF_OPEN: "ACTIVE — TP1 pending (close 50% + move SL)",
            STATE_TRAIL: "TRAILING — TP1 hit, SL at break-even, TP2 pending",
            STATE_DONE: "DONE — day finished",
        }

        print(f"\n{'='*60}")
        print(f"  {self.symbol}  |  {now.strftime('%Y-%m-%d %H:%M:%S')} NY")
        print(f"  State: {status.get(self.state, self.state)}")
        print(f"  Bid: {bid:.5f}  Ask: {ask:.5f}")

        if self.orb_high and self.orb_low:
            print(f"  ORB: {self.orb_high:.5f} / {self.orb_low:.5f}")
        else:
            print(f"  ORB: Building...")

        if self.state in (STATE_HALF_OPEN, STATE_TRAIL):
            direction = "LONG" if self.trade_long else "SHORT"
            print(f"  Position: {direction}  Entry: {self.entry_price:.5f}")
            print(f"  Volume: {self.current_volume} / {self.initial_volume}")
            print(f"  TP1: {self.tp1_price:.5f} ({'HIT' if self.tp1_hit else 'pending'})")
            print(f"  TP2: {self.tp2_price:.5f} ({'HIT' if self.tp2_hit else 'pending'})")
            print(f"  SL:  {self.sl_price:.5f}")
        print(f"{'='*60}")


def main():
    print("+----------------------------------------------+")
    print("|     ORB LIVE TRADING BOT — MetaTrader 5      |")
    print("|  Opening Range Breakout · New York Session   |")
    print("+----------------------------------------------+")

    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        sys.exit(1)

    print("MT5 initialized successfully.\n")

    account_info = mt5.account_info()
    if account_info:
        print(f"  Account: {account_info.login}")
        print(f"  Server:  {account_info.server}")
        print(f"  Balance: ${account_info.balance:,.2f}")
        print(f"  Free:    ${account_info.margin_free:,.2f}")
        print()

    symbol = input("Enter symbol (e.g. XAUUSD): ").strip().upper()
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"Symbol '{symbol}' not found. Available symbols:")
        symbols = mt5.symbols_get()
        for s in symbols[:20]:
            print(f"  {s.name}")
        mt5.shutdown()
        sys.exit(1)

    mt5.symbol_select(symbol, True)

    lots_str = input("Enter lot size (e.g. 0.02): ").strip()
    lots = float(lots_str)

    print(f"\n  Symbol: {symbol}  |  Lots: {lots}")
    print(f"  Range:  {RANGE_START} — {RANGE_END} NY")
    print(f"  Trade:  {TRADE_START} — {TRADE_END} NY")
    print(f"  TP1: +0.25% (close 50%, SL → entry)")
    print(f"  TP2: +0.50% (close rest)")
    print(f"  SL:  -0.25% (close all)")
    print(f"\n  Press Ctrl+C to emergency stop\n")

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
        print(f"  Found {len(rates)} existing M1 bars for today")
        # Process existing bars to build range if applicable
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
            print(f"  ORB range already built: {bot.orb_high:.5f} / {bot.orb_low:.5f}")

    print("\nBot is running. Monitoring ticks...\n")

    status_counter = 0

    try:
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

            # Print status every 5 seconds
            status_counter += 1
            if status_counter >= 50:  # ~5 seconds at 100ms sleep
                bot.print_status()
                status_counter = 0

            # Sleep 100ms for tick updates
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\nCtrl+C detected — emergency stop...")
        bot.emergency_stop()
        bot.print_status()
    finally:
        db.generate_all_html()
        print("Exported all.html")
        mt5.shutdown()
        print("MT5 shutdown complete.")


if __name__ == '__main__':
    main()
