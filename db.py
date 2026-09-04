import json
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
ALL_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all.json")


def _get_day_dir(d: date) -> str:
    day_dir = os.path.join(DB_DIR, d.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    return day_dir


def _get_day_json(d: date) -> str:
    return os.path.join(_get_day_dir(d), "db.json")


def _get_day_html(d: date) -> str:
    return os.path.join(_get_day_dir(d), "index.html")


def _load_json(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def _save_json(path: str, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _now_ny() -> str:
    return datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def log_event(event_type: str, data: dict):
    record = {
        "timestamp": _now_ny(),
        "type": event_type,
        **data,
    }
    today = datetime.now(NY_TZ).date()
    day_json = _get_day_json(today)
    all_json_path = ALL_JSON

    day_trades = _load_json(day_json)
    day_trades.append(record)
    _save_json(day_json, day_trades)

    all_trades = _load_json(all_json_path)
    all_trades.append(record)
    _save_json(all_json_path, all_trades)

    generate_day_html(today)
    generate_all_html()


def generate_day_html(d: date):
    day_json = _get_day_json(d)
    trades = _load_json(day_json)
    day_html_path = _get_day_html(d)
    _write_html(day_html_path, f"ORB Trade Log — {d.strftime('%Y-%m-%d')}", trades)


def generate_all_html():
    all_trades = _load_json(ALL_JSON)
    _write_html(ALL_JSON.replace(".json", ".html"), "ORB Trade Log — All Days", all_trades)


def _write_html(path: str, title: str, trades: list):
    summary = {"LONG": 0, "SHORT": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
    for t in trades:
        if t["type"] in ("ENTRY_LONG", "ENTRY_SHORT"):
            direction = "LONG" if t["type"] == "ENTRY_LONG" else "SHORT"
            summary[direction] += 1
        if t["type"] in ("TP2_HIT", "SL_HIT", "FORCE_CLOSE", "EMERGENCY_CLOSE", "TRAIL_CLOSE"):
            pnl = t.get("pnl", 0)
            summary["total_pnl"] += pnl
            if pnl >= 0:
                summary["wins"] += 1
            else:
                summary["losses"] += 1

    rows = ""
    for t in trades:
        cls = ""
        if t["type"] in ("TP2_HIT", "TRAIL_CLOSE") and t.get("pnl", 0) >= 0:
            cls = ' class="win"'
        elif t["type"] in ("SL_HIT",) or t.get("pnl", 0) < 0:
            cls = ' class="loss"'
        elif "ENTRY" in t["type"]:
            cls = ' class="entry"'

        pnl_val = t.get("pnl")
        pnl_str = f"${pnl_val:+.2f}" if pnl_val is not None else "-"
        pnl_cls = ""
        if pnl_val is not None:
            pnl_cls = "win" if pnl_val >= 0 else "loss"

        rows += f"""<tr{cls}>
  <td>{t.get('timestamp','')}</td>
  <td>{t.get('type','')}</td>
  <td>{t.get('direction','')}</td>
  <td>{t.get('entry','')}</td>
  <td>{t.get('tp1','')}</td>
  <td>{t.get('tp2','')}</td>
  <td>{t.get('sl','')}</td>
  <td>{t.get('volume','')}</td>
  <td>{t.get('close_price','')}</td>
  <td>{t.get('orb_high','')}</td>
  <td>{t.get('orb_low','')}</td>
  <td class="{pnl_cls}">{pnl_str}</td>
  <td>{t.get('comment','')}</td>
</tr>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', system-ui, sans-serif; padding: 24px; }}
  h1 {{ color: #58a6ff; margin-bottom: 8px; font-size: 1.6em; }}
  .summary {{ display: flex; gap: 16px; margin: 16px 0 24px; flex-wrap: wrap; }}
  .summary .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 14px 20px; min-width: 130px;
  }}
  .summary .card .label {{ color: #8b949e; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.5px; }}
  .summary .card .value {{ font-size: 1.4em; font-weight: 700; margin-top: 4px; }}
  .summary .card .value.green {{ color: #3fb950; }}
  .summary .card .value.red {{ color: #f85149; }}
  .summary .card .value.blue {{ color: #58a6ff; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  th {{ background: #161b22; color: #8b949e; text-transform: uppercase; font-size: 0.7em;
       letter-spacing: 0.5px; padding: 10px 12px; text-align: left; border-bottom: 2px solid #30363d;
       position: sticky; top: 0; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
  tr:hover {{ background: #161b22; }}
  tr.entry {{ background: #1c2530; }}
  tr.win {{ background: #0d2818; }}
  tr.loss {{ background: #2d1215; }}
  .win {{ color: #3fb950; }}
  .loss {{ color: #f85149; }}
  .no-data {{ text-align: center; padding: 60px; color: #484f58; font-size: 1.1em; }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .nav {{ margin-bottom: 20px; color: #8b949e; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="nav"><a href="../index.html">All Days</a></div>
<div class="summary">
  <div class="card"><div class="label">Total Trades</div><div class="value blue">{summary['LONG'] + summary['SHORT']}</div></div>
  <div class="card"><div class="label">Long</div><div class="value blue">{summary['LONG']}</div></div>
  <div class="card"><div class="label">Short</div><div class="value blue">{summary['SHORT']}</div></div>
  <div class="card"><div class="label">Wins</div><div class="value green">{summary['wins']}</div></div>
  <div class="card"><div class="label">Losses</div><div class="value red">{summary['losses']}</div></div>
  <div class="card"><div class="label">Total PnL</div><div class="value {'green' if summary['total_pnl'] >= 0 else 'red'}">${summary['total_pnl']:+.2f}</div></div>
</div>
<table>
<thead>
<tr>
  <th>Time</th><th>Type</th><th>Dir</th><th>Entry</th><th>TP1</th><th>TP2</th>
  <th>SL</th><th>Vol</th><th>Close</th><th>ORB H</th><th>ORB L</th><th>PnL</th><th>Note</th>
</tr>
</thead>
<tbody>
{rows if rows else '<tr><td colspan="13" class="no-data">No trades recorded</td></tr>'}
</tbody>
</table>
</body>
</html>"""
    with open(path, "w") as f:
        f.write(html)


def get_day_summary(d: date) -> dict:
    day_json = _get_day_json(d)
    trades = _load_json(day_json)
    return {"date": d.strftime("%Y-%m-%d"), "trades": trades, "count": len(trades)}


def get_all_summary() -> dict:
    trades = _load_json(ALL_JSON)
    days = set()
    for t in trades:
        ts = t.get("timestamp", "")
        if ts:
            days.add(ts[:10])
    return {"total_trades": len(trades), "days": sorted(days), "trades": trades}
