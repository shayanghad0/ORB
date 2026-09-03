import json, datetime

with open("XAUUSD_2026-09-02_M1.json") as f:
    bars = json.load(f)

for start_min, end_min in [(30,36), (30,35), (31,36), (30,37)]:
    orb_h = None
    orb_l = None
    for b in bars:
        t = datetime.datetime.fromisoformat(b["time"]).time()
        if datetime.time(9, start_min) <= t < datetime.time(9, end_min):
            if orb_h is None:
                orb_h = b["high"]
                orb_l = b["low"]
            else:
                orb_h = max(orb_h, b["high"])
                orb_l = min(orb_l, b["low"])

    prev_c = None
    first_sig = None
    for b in bars:
        t = datetime.datetime.fromisoformat(b["time"]).time()
        if datetime.time(9, 36) <= t < datetime.time(11, 30):
            c = b["close"]
            if prev_c is not None and c > orb_h and prev_c <= orb_h:
                first_sig = f"LONG at {t} C={c} > ORB_H={orb_h}"
                break
            if prev_c is not None and c < orb_l and prev_c >= orb_l:
                first_sig = f"SHORT at {t} C={c} < ORB_L={orb_l}"
                break
            prev_c = c

    print(f"Range 09:{start_min:02d}-09:{end_min:02d} => ORB H={orb_h} L={orb_l} => {first_sig}")
