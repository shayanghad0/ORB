import MetaTrader5 as mt5
import datetime
import time
import sys
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

RANGE_START = datetime.time(9, 31)
RANGE_END   = datetime.time(9, 37)   # exclusive
TRADE_START = datetime.time(9, 36)
TRADE_END   = datetime.time(11, 30)  # exclusive

TP_PCT   = 0.005    # 0.5 % full TP
SL_PCT   = 0.0025   # 0.25 % initial SL
HALF_PCT = 0.0025   # 0.25 % = half of TP → close 50 %
TRAIL_SL = 0.00125  # 0.125 % = move SL to this after half-TP

LOT_SIZE = 0.02
HALF_LOT = 0.01

POLL_MS = 100  # milliseconds between price checks


def log(msg):
    now = datetime.datetime.now(NY_TZ).strftime("%H:%M:%S.%f")[:-3]
    print(f"[{now}] {msg}", flush=True)


def get_tick(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None, None
    return tick.ask, tick.bid


def get_latest_bars(symbol, count):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
    if rates is None or len(rates) == 0:
        return []
    bars = []
    for r in rates:
        dt = datetime.datetime.fromtimestamp(r[0], tz=NY_TZ)
        bars.append({
            'time': dt, 'open': r[1], 'high': r[2],
            'low': r[3], 'close': r[4],
        })
    return bars


def build_orb(bars):
    orb_high = None
    orb_low  = None
    for b in bars:
        t = b['time'].time()
        if RANGE_START <= t < RANGE_END:
            if orb_high is None:
                orb_high = b['high']
                orb_low  = b['low']
            else:
                orb_high = max(orb_high, b['high'])
                orb_low  = min(orb_low,  b['low'])
    return orb_high, orb_low


def send_order(symbol, order_type, lots, sl=None, tp=None, comment="ORB"):
    info = mt5.symbol_info(symbol)
    if info is None:
        log(f"ERROR: symbol_info returned None for {symbol}")
        return None

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log("ERROR: cannot get tick")
        return None

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    point = info.point
    digits = info.digits

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "volume":    lots,
        "type":      order_type,
        "price":     price,
        "deviation": 30,
        "magic":     234000,
        "comment":   comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_TYPE_FILLING_IOC,
    }

    if sl is not None:
        request["sl"] = round(sl, digits)
    if tp is not None:
        request["tp"] = round(tp, digits)

    result = mt5.order_send(request)
    if result is None:
        log(f"ERROR: order_send returned None — {mt5.last_error()}")
        return None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"ERROR: order failed — {result.retcode} {result.comment}")
        return None

    log(f"ORDER OK — ticket={result.order} price={result.price} lots={lots}")
    return result


def close_position(ticket, symbol, lots, reason="close"):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        log(f"WARNING: position {ticket} not found for close")
        return None

    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "volume":    lots,
        "type":      close_type,
        "position":  ticket,
        "price":     price,
        "deviation": 30,
        "magic":     234000,
        "comment":   reason,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_TYPE_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = result.comment if result else str(mt5.last_error())
        log(f"ERROR closing {ticket}: {err}")
        return None

    log(f"CLOSED ticket={ticket} lots={lots} reason={reason}")
    return result


def modify_sl(ticket, symbol, new_sl):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    info = mt5.symbol_info(symbol)
    digits = info.digits

    request = {
        "action":    mt5.TRADE_ACTION_SLTP,
        "symbol":    symbol,
        "position":  ticket,
        "sl":        round(new_sl, digits),
        "tp":        p.tp,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"SL modified to {new_sl:.{digits}f} for ticket={ticket}")
    else:
        err = result.comment if result else str(mt5.last_error())
        log(f"ERROR modifying SL: {err}")


def run_bot():
    if not mt5.initialize():
        log("MT5 initialization failed. Is MetaTrader 5 running?")
        sys.exit(1)

    account = mt5.account_info()
    if account is None:
        log("ERROR: cannot get account info")
        mt5.shutdown()
        sys.exit(1)

    log(f"Connected — {account.server} | Login: {account.login} | Balance: {account.balance}")

    symbol = input("Enter symbol (e.g. XAUUSD): ").strip().upper()
    info = mt5.symbol_info(symbol)
    if info is None:
        log(f"Symbol '{symbol}' not found")
        mt5.shutdown()
        return
    mt5.symbol_select(symbol, True)
    log(f"Symbol {symbol} selected — digits={info.digits} point={info.point} spread={info.spread}")

    # ── state ──
    STATE_IDLE       = 0
    STATE_BUILDING   = 1
    STATE_WAIT_BREAK = 2
    STATE_HALF_OPEN  = 3
    STATE_TRAIL      = 4

    state = STATE_IDLE
    orb_high = None
    orb_low  = None
    prev_close = None

    ticket = None
    entry_price = None
    is_long = None
    half_closed = False
    today_date = None

    log("Bot started. Waiting for market open...")

    try:
        while True:
            now_ny = datetime.datetime.now(NY_TZ)
            t = now_ny.time()
            today = now_ny.date()

            # ── reset at new day ──
            if today_date != today:
                today_date = today
                state = STATE_IDLE
                orb_high = None
                orb_low  = None
                prev_close = None
                ticket = None
                entry_price = None
                is_long = None
                half_closed = False
                log(f"=== New day: {today} ===")

            ask, bid = get_tick(symbol)
            if ask is None:
                time.sleep(POLL_MS / 1000)
                continue

            mid = (ask + bid) / 2

            # ── IDLE → BUILDING ──
            if state == STATE_IDLE and RANGE_START <= t < RANGE_END:
                bars = get_latest_bars(symbol, 10)
                orb_high, orb_low = build_orb(bars)
                state = STATE_BUILDING
                log(f"Building range — current ORB H={orb_high} L={orb_low}")

            # ── BUILDING → WAIT_BREAK ──
            if state == STATE_BUILDING:
                if t >= RANGE_END:
                    state = STATE_WAIT_BREAK
                    log(f"Range locked — ORB High={orb_high:.{info.digits}f}  Low={orb_low:.{info.digits}f}")
                else:
                    bars = get_latest_bars(symbol, 10)
                    new_h, new_l = build_orb(bars)
                    if new_h is not None:
                        orb_high, orb_low = new_h, new_l

            # ── WAIT_BREAK → open trade ──
            if state == STATE_WAIT_BREAK and TRADE_START <= t < TRADE_END:
                if prev_close is not None:
                    # LONG breakout
                    if mid > orb_high and prev_close <= orb_high:
                        sl = entry_price * (1 - SL_PCT) if entry_price else mid * (1 - SL_PCT)
                        tp = mid * (1 + TP_PCT)
                        res = send_order(symbol, mt5.ORDER_TYPE_BUY, LOT_SIZE,
                                         sl=mid * (1 - SL_PCT), tp=tp, comment="ORB_L")
                        if res:
                            ticket = res.order
                            entry_price = mid
                            is_long = True
                            half_closed = False
                            state = STATE_HALF_OPEN
                            log(f"LONG entry @ {mid:.{info.digits}f}  TP={tp:.{info.digits}f}  SL={mid*(1-SL_PCT):.{info.digits}f}")

                    # SHORT breakout
                    elif mid < orb_low and prev_close >= orb_low:
                        sl = mid * (1 + SL_PCT)
                        tp = mid * (1 - TP_PCT)
                        res = send_order(symbol, mt5.ORDER_TYPE_SELL, LOT_SIZE,
                                         sl=sl, tp=tp, comment="ORB_S")
                        if res:
                            ticket = res.order
                            entry_price = mid
                            is_long = False
                            half_closed = False
                            state = STATE_HALF_OPEN
                            log(f"SHORT entry @ {mid:.{info.digits}f}  TP={tp:.{info.digits}f}  SL={sl:.{info.digits}f}")

            # ── HALF_OPEN → manage partial close + trail ──
            if state == STATE_HALF_OPEN and ticket is not None:
                pos = mt5.positions_get(ticket=ticket)
                if not pos:
                    log("Position closed externally — resetting")
                    state = STATE_WAIT_BREAK
                    ticket = None
                else:
                    p = pos[0]
                    if is_long:
                        # half TP hit?
                        if not half_closed and mid >= entry_price * (1 + HALF_PCT):
                            close_result = close_position(ticket, symbol, HALF_LOT, reason="half_tp")
                            if close_result:
                                half_closed = True
                                new_sl = entry_price * (1 + TRAIL_SL)
                                modify_sl(ticket, symbol, new_sl)
                                state = STATE_TRAIL
                                log(f"Half TP hit — closed {HALF_LOT} lots, SL moved to {new_sl:.{info.digits}f}")
                    else:
                        if not half_closed and mid <= entry_price * (1 - HALF_PCT):
                            close_result = close_position(ticket, symbol, HALF_LOT, reason="half_tp")
                            if close_result:
                                half_closed = True
                                new_sl = entry_price * (1 - TRAIL_SL)
                                modify_sl(ticket, symbol, new_sl)
                                state = STATE_TRAIL
                                log(f"Half TP hit — closed {HALF_LOT} lots, SL moved to {new_sl:.{info.digits}f}")

            # ── TRAIL → full TP or end of day ──
            if state == STATE_TRAIL and ticket is not None:
                pos = mt5.positions_get(ticket=ticket)
                if not pos:
                    log("Remaining position closed (TP or SL hit)")
                    state = STATE_WAIT_BREAK
                    ticket = None
                else:
                    full_tp_hit = False
                    if is_long and mid >= entry_price * (1 + TP_PCT):
                        full_tp_hit = True
                    elif not is_long and mid <= entry_price * (1 - TP_PCT):
                        full_tp_hit = True

                    if full_tp_hit:
                        close_position(ticket, symbol, HALF_LOT, reason="full_tp")
                        log("Full TP hit — day complete")
                        state = STATE_IDLE
                        ticket = None

            # ── end of day force close ──
            if t >= TRADE_END and ticket is not None:
                log("End of trade session — force closing")
                close_position(ticket, symbol, HALF_LOT, reason="eod_force")
                state = STATE_IDLE
                ticket = None

            # ── log price ──
            if state in (STATE_WAIT_BREAK, STATE_HALF_OPEN, STATE_TRAIL):
                sys.stdout.write(f"\r  {now_ny.strftime('%H:%M:%S')}  bid={bid:.{info.digits}f}  ask={ask:.{info.digits}f}  state={state}  ")
                sys.stdout.flush()

            prev_close = mid
            time.sleep(POLL_MS / 1000)

    except KeyboardInterrupt:
        log("\nBot stopped by user")
        if ticket is not None:
            log("Force closing open position before exit...")
            close_position(ticket, symbol, HALF_LOT, reason="shutdown")
    finally:
        mt5.shutdown()
        log("MT5 shut down")


if __name__ == '__main__':
    run_bot()
