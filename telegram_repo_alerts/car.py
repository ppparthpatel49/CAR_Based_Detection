"""
car.py — Weekly CAR (Cumulative Average Reversal) report engine.

Implements the method exactly as in the user's reference sheet:

  * Year high = max **Close** in the trailing 365 calendar days
    (validated: reproduces the sheet's exact 6-stock list for 2026-W39 —
     KOTAKBANK, PNB, BAJAJHLDNG, TECHM, GAIL, ETERNAL).
  * CAR = running average of closes from the year-high date onward.
  * Rating "Buy/Average Out" when that average has risen for >= `car_days`
    (default 10) consecutive trading days; otherwise "Avoid Hold".
  * GTT trigger = the LAST COMPLETED week's (Mon–Fri) intraday high —
    the level that stays fixed all week (Sunday-ritual rule); limit = +0.10;
    qty = one ₹5,000 tranche rounded up.
  * Difference from 200 DMA = % above the 200-day simple moving average.

Also provides: append-only CSV log of results, and Telegram HTML formatting.
Standard library only.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

TRANCHE = 5000            # rupees per entry (capital / 40 style tranche)
DMA_WINDOW = 200
RATING_BUY = "Buy/Average Out"
RATING_AVOID = "Avoid Hold"
LOG_COLUMNS = [
    "run_timestamp", "iso_week", "week_start", "week_end", "nse_code",
    "cmp", "diff_200dma_pct", "car_rating", "gtt_trigger", "gtt_limit",
    "qty_5000", "car_streak", "year_high_date", "year_high_close", "price_source",
]


# --------------------------------------------------------------------------- data
def load_prices(path: str | Path) -> dict[str, list[dict]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"❌ {path} not found — run: python -m telegram_repo_alerts download")
    by_sym: dict[str, list[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                by_sym[row["symbol"]].append({
                    "date": row["date"],
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                })
            except (KeyError, ValueError):
                continue
    for sym in by_sym:
        by_sym[sym].sort(key=lambda r: r["date"])
    return by_sym


def sma(rows: list[dict], window: int = DMA_WINDOW) -> float | None:
    closes = [r["close"] for r in rows]
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


# ----------------------------------------------------------------------- analysis
def analyze(sym: str, rows: list[dict], car_days: int, week_start: str,
            week_end: str) -> dict:
    last_date = rows[-1]["date"]
    cutoff = (datetime.fromisoformat(last_date) - timedelta(days=365)).date().isoformat()
    year_window = [r for r in rows if r["date"] >= cutoff] or rows

    # year high on CLOSE basis (matches the reference sheet)
    yh = max(year_window, key=lambda r: r["close"])
    yh_date = yh["date"]

    # running cumulative average of closes from the year-high date
    series = [r for r in rows if r["date"] >= yh_date]
    avgs: list[float] = []
    total = 0.0
    for i, r in enumerate(series, 1):
        total += r["close"]
        avgs.append(total / i)

    def streak_as_of(end_date: str | None = None) -> int:
        n = len(avgs) if end_date is None else \
            (max((i for i, r in enumerate(series) if r["date"] <= end_date),
                 default=-1) + 1)
        s = 0
        for i in range(n - 1, 0, -1):
            if avgs[i] > avgs[i - 1]:
                s += 1
            else:
                break
        return s

    streak = streak_as_of()
    prev_fri = (datetime.fromisoformat(week_start) - timedelta(days=3)).date().isoformat()
    week_rows = [r for r in rows if week_start <= r["date"] <= week_end]
    week_high = max((r["high"] for r in week_rows), default=float("nan"))
    last_close = rows[-1]["close"]
    dma = sma(rows)
    diff_pct = round((last_close - dma) / dma * 100, 2) if dma else ""

    positive = streak >= car_days
    return {
        "symbol": sym,
        "nse_code": f"NSE:{sym}",
        "cmp": round(last_close, 2),
        "diff_200dma_pct": diff_pct,
        "car_rating": RATING_BUY if positive else RATING_AVOID,
        "car_positive": positive,
        "car_streak": streak,
        "car_avg": round(avgs[-1], 2) if avgs else "",
        "year_high_date": yh_date,
        "year_high": round(yh["close"], 2),
        "last_date": last_date,
        "week_high": round(week_high, 2) if week_rows else "",
        "trigger": round(week_high, 2) if week_rows else "",
        "limit": round(week_high + 0.10, 2) if week_rows else "",
        "qty_5000": math.ceil(TRANCHE / week_high) if week_rows and week_high > 0 else "",
        "fresh_this_week": positive and streak_as_of(prev_fri) < car_days,
    }


def week_bounds(prices: dict[str, list[dict]], week_start: str | None = None
                ) -> tuple[str, str]:
    """Mon–Fri of the LAST COMPLETED week (the GTT trigger window).
    While the data's week is still in progress (latest row Mon–Thu), the
    window is the week before — the trigger must stay fixed all week."""
    latest = max(r["date"] for rows in prices.values() for r in rows)
    if week_start:
        start = week_start
    else:
        d = datetime.fromisoformat(latest)
        monday = d - timedelta(days=d.weekday())
        if d.weekday() < 4:          # Mon–Thu: this week not finished yet
            monday -= timedelta(days=7)
        start = monday.date().isoformat()
    end = (datetime.fromisoformat(start) + timedelta(days=4)).date().isoformat()
    return start, min(end, latest)


def run_analysis(prices_path: str | Path, car_days: int = 10,
                 week_start: str | None = None) -> dict:
    prices = load_prices(prices_path)
    if not prices:
        raise ValueError("❌ No price rows found — run: python -m telegram_repo_alerts download")
    start, end = week_bounds(prices, week_start)
    results = [analyze(s, rows, car_days, start, end)
               for s, rows in sorted(prices.items())]
    latest = max(r["date"] for rows in prices.values() for r in rows)
    iso = datetime.fromisoformat(start).isocalendar()   # label = trigger window
    positives = [r for r in results if r["car_positive"]]
    near = sorted((r for r in results if car_days - 5 <= r["car_streak"] < car_days),
                  key=lambda x: -x["car_streak"])
    return {
        "results": results, "positives": positives, "near_misses": near,
        "week_start": start, "week_end": end, "data_as_of": latest,
        "iso_year": iso.year, "iso_week": iso.week, "car_days": car_days,
        "scanned": len(results),
        "fresh": [r for r in positives if r["fresh_this_week"]],
    }


# --------------------------------------------------------------------------- log
def append_log(report: dict, log_path: str | Path, log_all: bool = False) -> int:
    """Append this run's rows to the log CSV. Returns number of rows written."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = report["results"] if log_all else report["positives"]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow({
                "run_timestamp": stamp,
                "iso_week": f"{report['iso_year']}-W{report['iso_week']:02d}",
                "week_start": report["week_start"],
                "week_end": report["week_end"],
                "nse_code": r["nse_code"],
                "cmp": r["cmp"],
                "diff_200dma_pct": r["diff_200dma_pct"],
                "car_rating": r["car_rating"],
                "gtt_trigger": r["trigger"],
                "gtt_limit": r["limit"],
                "qty_5000": r["qty_5000"],
                "car_streak": r["car_streak"],
                "year_high_date": r["year_high_date"],
                "year_high_close": r["year_high"],
                "price_source": "yfinance daily close",
            })
    return len(rows)


# --------------------------------------------------------------------- rendering
def positives_sorted(report: dict) -> list[dict]:
    """Sort like the reference sheet: Difference from 200 DMA ascending."""
    def key(r):
        d = r.get("diff_200dma_pct")
        return (0, d, r["symbol"]) if d != "" else (1, 0.0, r["symbol"])
    return sorted(report["positives"], key=key)


def pre_table(report: dict) -> str:
    """Monospace table mirroring the reference sheet columns & order."""
    rows = positives_sorted(report)
    if not rows:
        return "<pre>⚪ No CAR-positive stocks this week.</pre>"
    lines = [
        f"{'NSE Code':<16}{'CMP':>9}   {'Difference from 200 DMA':>24}"
        f"   {'CAR Rating':<18}{'Trigger Price for GTT':>22}",
    ]
    for r in rows:
        diff = f"{r['diff_200dma_pct']}" if r["diff_200dma_pct"] != "" else "n/a"
        lines.append(f"{r['nse_code']:<16}{r['cmp']:>9}   {diff:>24}"
                     f"   {r['car_rating']:<18}{r['trigger']:>22}")
    return "<pre>\n" + "\n".join(lines) + "\n</pre>"


def qty_line(report: dict) -> str:
    rows = positives_sorted(report)
    if not rows:
        return ""
    return "🛒 Limit/qty: " + " · ".join(
        f"{r['symbol']} qty {r['qty_5000']} @ {r['limit']}" for r in rows)


def near_miss_line(report: dict) -> str:
    if not report.get("near_misses"):
        return ""
    nm = ", ".join(f"{r['symbol']}({r['car_streak']})" for r in report["near_misses"][:7])
    return f"👀 Near-miss: {nm}"


def console_report(report: dict) -> str:
    lines = []
    lines.append("=" * 88)
    lines.append(f"📈 CAR WEEKLY REPORT — ISO {report['iso_year']}-W{report['iso_week']:02d}  "
                 f"(week {report['week_start']} .. {report['week_end']}, "
                 f"data as of {report['data_as_of']})")
    lines.append("=" * 88)
    lines.append(f"Scanned: {report['scanned']} stocks · CAR rule: avg rising >= "
                 f"{report['car_days']} consecutive days from year high (close basis)")
    lines.append(f"✅ {RATING_BUY}: {len(report['positives'])}   "
                 f"🆕 fresh this week: {len(report['fresh'])}   "
                 f"⛔ {RATING_AVOID}: {report['scanned'] - len(report['positives'])}")
    if report["positives"]:
        lines.append("\n--- CAR POSITIVE (Sunday's GTT list, ₹5,000 tranche) " + "-" * 34)
        header = (f"{'NSE Code':<16}{'CMP':>10}{'200DMA%':>9}  {'CAR Rating':<16}"
                  f"{'Trigger':>10}{'Limit':>9}{'Qty':>5}{'Streak':>7}  FRESH")
        lines.append(header)
        for r in positives_sorted(report):
            lines.append(
                f"{r['nse_code']:<16}{r['cmp']:>10}{r['diff_200dma_pct']:>9}  "
                f"{r['car_rating']:<16}{r['trigger']:>10}{r['limit']:>9}"
                f"{r['qty_5000']:>5}{r['car_streak']:>7}  {'⭐' if r['fresh_this_week'] else ''}")
    if report["near_misses"]:
        nm = ", ".join(f"{r['symbol']}({r['car_streak']})" for r in report["near_misses"])
        lines.append(f"\n👀 Near-miss (streak {report['car_days']-5}–{report['car_days']-1}): {nm}")
    lines.append("\n⚠️ Educational output only — not investment advice.")
    return "\n".join(lines)


def format_message(report: dict, log_note: str = "") -> str:
    """Telegram HTML message for the `report` command (sheet-style)."""
    tag = f"{report['iso_year']}-W{report['iso_week']:02d}"
    pos = positives_sorted(report)
    lines = [
        f"📈 <b>CAR Weekly Report</b> — {tag}",
        f"🗓 {report['week_start']} → {report['week_end']} · data as of "
        f"{report['data_as_of']} · {report['scanned']} stocks scanned",
        f"✅ <b>{len(pos)} CAR positive ({RATING_BUY})</b> · 🆕 fresh: {len(report['fresh'])}"
        f" · ⛔ avoid: {report['scanned'] - len(pos)}",
        "",
        pre_table(report),
    ]
    qty = qty_line(report)
    if qty:
        lines += ["", qty]
    nm = near_miss_line(report)
    if nm:
        lines.append(nm)
    if log_note:
        lines += ["", f"📄 {log_note}"]
    lines.append("<i>Educational only — not investment advice.</i>")
    return "\n".join(lines)


def format_daily_message(report: dict, now: datetime) -> str:
    """
    The daily 5 PM Telegram message: ONLY the CAR result TABLE — exactly the
    reference sheet's columns/rows. No event lines (GTT/flip/move events are
    reported in the console/Actions run log instead).
    """
    tag = f"{report['iso_year']}-W{report['iso_week']:02d}"
    pos = positives_sorted(report)
    lines = [
        f"📈 <b>Daily CAR Result</b> — {now.strftime('%a %d %b %Y')} · {tag}",
        "",
        f"✅ <b>{len(pos)} CAR positive ({RATING_BUY})</b> · "
        f"⛔ avoid: {report['scanned'] - len(pos)} · data as of {report['data_as_of']}",
        "",
        pre_table(report),
    ]
    qty = qty_line(report)
    if qty:
        lines += ["", qty]
    nm = near_miss_line(report)
    if nm:
        lines.append(nm)
    lines.append("<i>Educational only — not investment advice.</i>")
    return "\n".join(lines)
