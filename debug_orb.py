import json, datetime

with open("XAUUSD_2026-09-02_M1.json") as f:
    bars = json.load(f)

orb_high = None
orb_low = None
for b in bars:
    t = datetime.datetime.fromisoformat(b["time"]).time()
    if datetime.time(9, 30) <= t < datetime.time(9, 36):
        if orb_high is None:
            orb_high = b["high"]
            orb_low = b["low"]
        else:
            orb_high = max(orb_high, b["high"])
            orb_low = min(orb_low, b["low"])
        print(f"{t}  H={b['high']}  L={b['low']}  => ORB: {orb_high} / {orb_low}")

print(f"\nFinal ORB High={orb_high}  Low={orb_low}")
print()

prev_close = None
for b in bars:
    t = datetime.datetime.fromisoformat(b["time"]).time()
    if datetime.time(9, 36) <= t < datetime.time(10, 10):
        c = b["close"]
        cross_up = c > orb_high and prev_close is not None and prev_close <= orb_high
        cross_down = c < orb_low and prev_close is not None and prev_close >= orb_low
        marker = " <<LONG" if cross_up else (" <<SHORT" if cross_down else "")
        pc = f"{prev_close}" if prev_close is not None else "N/A"
        print(f"{t}  O={b['open']}  H={b['high']}  L={b['low']}  C={c}  prevC={pc}{marker}")
        prev_close = c
