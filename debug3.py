import json, datetime

with open("XAUUSD_2026-09-02_M1.json") as f:
    bars = json.load(f)

# Use Pine Script exact conditions (no crossover check - just close vs level)
orb_h = None
orb_l = None
for b in bars:
    t = datetime.datetime.fromisoformat(b["time"]).time()
    if datetime.time(9, 30) <= t < datetime.time(9, 36):
        if orb_h is None:
            orb_h = b["high"]
            orb_l = b["low"]
        else:
            orb_h = max(orb_h, b["high"])
            orb_l = min(orb_l, b["low"])

print(f"ORB H={orb_h} L={orb_l}")
print()

# Pine Script: bullish_bo = close > orb_high and close[1] <= orb_high
# Pine Script: bearish_bo = close < orb_low  and close[1] >= orb_low
# This is EXACTLY the crossover check. Let me verify the SHORT bar more carefully

for b in bars:
    t = datetime.datetime.fromisoformat(b["time"]).time()
    if datetime.time(9, 48) <= t < datetime.time(9, 55):
        c = b["close"]
        h = b["high"]
        lo = b["low"]
        print(f"{t} O={b['open']} H={h} L={lo} C={c}")
        if c > orb_h:
            print(f"  -> close {c} > orb_high {orb_h} = True (would be LONG if prev <= orb_high)")
        if c < orb_l:
            print(f"  -> close {c} < orb_low {orb_l} = True (would be SHORT if prev >= orb_low)")
        print(f"  -> close == orb_low? {c == orb_l}, close < orb_low? {c < orb_l}, diff = {c - orb_l}")
