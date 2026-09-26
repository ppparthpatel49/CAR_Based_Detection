"""
alerts.py — Market alert engine: detects events and sends them to Telegram.

Alert types (all toggleable in config.json → "alerts"):
  * gtt_trigger — a CAR-positive stock's price crosses the previous week's
    high (the level where its GTT order would have executed).
  * car_flip    — a stock's CAR status flipped: negative → "Buy/Average Out"
    (🟢) or positive → "Avoid Hold" (🔴).
  * daily_move  — a stock moved more than `daily_move_pct` (default 3%)
    versus its previous close.

De-duplication: every alert gets a key (type:symbol:period) that is stored in
`logs/alerts_state.json`. Already-sent keys are skipped, so the GitHub Actions
workflow (or any scheduler) can run as often as it likes without spamming.
The state file is committed back to the repo by the workflow so it survives
across ephemeral runners.

Standard library only (yfinance is used indirectly via market_data).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import car, config as cfg

ROOT = Path(__file__).resolve().parent.parent
IST = ZoneInfo("Asia/Kolkata")
KEEP_STATE_DAYS = 45


# ------------------------------------------------------------------------ state
def load_state(path: str | Path) -> dict:
    path = Path(path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            if isinstance(state, dict):
                state.setdefault("positives", [])
                state.setdefault("sent", {})
                return state
        except (json.JSONDecodeError, OSError):
            pass
    return {"positives": [], "sent": {}, "updated_at": ""}


def save_state(path: str | Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(IST).isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)


def _prune_sent(state: dict) -> None:
    cutoff = datetime.now(IST) - timedelta(days=KEEP_STATE_DAYS)
    keep = {}
    for key, ts in state.get("sent", {}).items():
        try:
            when = datetime.fromisoformat(ts)
            if when.tzinfo is None:
                when = when.replace(tzinfo=IST)
        except (ValueError, TypeError):
            continue
        if when >= cutoff:
            keep[key] = ts
    state["sent"] = keep


# ------------------------------------------------------------------- computations
def _monday(d: datetime) -> datetime:
    return (d - timedelta(days=d.weekday()))


def completed_week_bounds(now: datetime | None = None) -> tuple[str, str]:
    """Mon–Fri of the week BEFORE the current calendar week (the week whose
    high is the live GTT trigger during the current week)."""
    now = now or datetime.now(IST)
    prev_mon = _monday(now) - timedelta(days=7)
    return prev_mon.date().isoformat(), (prev_mon + timedelta(days=4)).date().isoformat()


def prev_week_highs(prices: dict[str, list[dict]]) -> dict[str, float]:
    start, end = completed_week_bounds()
    out: dict[str, float] = {}
    for sym, rows in prices.items():
        highs = [r["high"] for r in rows if start <= r["date"] <= end]
        if highs:
            out[sym] = round(max(highs), 2)
    return out


def latest_and_prev_closes(rows: list[dict]) -> tuple[float, float, str]:
    if len(rows) >= 2:
        return rows[-1]["close"], rows[-2]["close"], rows[-1]["date"]
    if rows:
        return rows[-1]["close"], rows[-1]["close"], rows[-1]["date"]
    return 0.0, 0.0, ""


def _iso_tag(date_str: str) -> str:
    try:
        iso = datetime.fromisoformat(date_str).isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    except ValueError:
        return date_str


# -------------------------------------------------------------------------- main
def check_alerts(config: dict | None = None, *, refresh: bool = True,
                 dry_run: bool = False, send: bool = True,
                 threshold: float | None = None, car_days: int | None = None
                 ) -> dict:
    """
    Detect new market alerts, de-duplicate against state, optionally send to
    Telegram. Returns a summary dict. `dry_run` prints but never persists or
    sends; `send=False` persists state but skips Telegram.
    """
    from .market_data import download_history, resolve_lists
    from .sender import send_text

    config = config if config is not None else cfg.load_config()
    alert_cfg = config.get("alerts", {})
    data_cfg = config.get("data", {})

    want_gtt = bool(alert_cfg.get("gtt_trigger", True))
    want_flip = bool(alert_cfg.get("car_flip", True))
    move_pct = threshold if threshold is not None else float(alert_cfg.get("daily_move_pct", 3.0) or 0)
    want_move = move_pct > 0
    car_days = car_days or int(alert_cfg.get("car_days", 10))
    state_path = alert_cfg.get("state_file", "logs/alerts_state.json")
    state_file = Path(state_path) if os.path.isabs(state_path) else ROOT / state_path
    prices_path = ROOT / data_cfg.get("output_dir", "data/prices") / "prices_daily.csv"

    # --- 1) refresh market data ------------------------------------------
    if refresh:
        lists = resolve_lists(config, data_cfg.get("source", "both"))
        merged: list[str] = []
        seen: set[str] = set()
        for _name, syms in lists:
            for s in syms:
                if s not in seen:
                    seen.add(s)
                    merged.append(s)
        print(f"⬇️  Refreshing {len(merged)} quote(s) for alerts …", flush=True)
        download_history(merged,
                         period=data_cfg.get("period", "2y"),
                         interval=data_cfg.get("interval", "1d"),
                         suffix=data_cfg.get("suffix", ".NS"),
                         output_dir=data_cfg.get("output_dir", "data/prices"))

    # --- 2) analyse current CAR status ------------------------------------
    report = car.run_analysis(prices_path, car_days=car_days)
    prices = car.load_prices(prices_path)
    positives = {r["symbol"] for r in report["positives"]}
    by_sym = {r["symbol"]: r for r in report["results"]}
    now = datetime.now(IST)
    today_tag = now.strftime("%Y-%m-%d")

    state = load_state(state_file)
    sent: dict[str, str] = state.get("sent", {})
    baseline = not state.get("positives") and not sent  # first ever run

    alerts: list[dict] = []

    # --- 3) GTT trigger alerts --------------------------------------------
    if want_gtt:
        highs = prev_week_highs(prices)
        wk = _iso_tag(completed_week_bounds()[0])
        for sym, trig in highs.items():
            if sym not in positives:
                continue
            close, _prev, _d = latest_and_prev_closes(prices.get(sym, []))
            if close and close >= trig:
                row = by_sym.get(sym, {})
                key = f"gtt:{sym}:{wk}"
                if key in sent:
                    continue
                sent[key] = now.isoformat(timespec="seconds")
                qty = row.get("qty_5000", "")
                alerts.append({
                    "key": key, "icon": "🚨", "symbol": sym,
                    "text": (f"🚨 <b>{row.get('nse_code', 'NSE:' + sym)}</b> crossed its "
                             f"GTT trigger <b>{trig}</b> — now {close} "
                             f"(limit {round(trig + 0.10, 2)}"
                             + (f", qty {qty}" if qty else "") + ")"),
                })

    # --- 4) CAR flip alerts -------------------------------------------------
    if want_flip:
        prev_pos = set(state.get("positives", []))
        wk = _iso_tag(report["data_as_of"] or today_tag)
        if not baseline:
            for sym in sorted(positives - prev_pos):
                key = f"car_up:{sym}:{wk}"
                if key in sent:
                    continue
                sent[key] = now.isoformat(timespec="seconds")
                row = by_sym.get(sym, {})
                alerts.append({
                    "key": key, "icon": "🟢", "symbol": sym,
                    "text": (f"🟢 <b>{row.get('nse_code', 'NSE:' + sym)}</b> CAR flipped "
                             f"POSITIVE → <b>Buy/Average Out</b> "
                             f"(streak {row.get('car_streak', '?')}d, CMP {row.get('cmp', '?')})"),
                })
            for sym in sorted(prev_pos - positives):
                key = f"car_down:{sym}:{wk}"
                if key in sent:
                    continue
                sent[key] = now.isoformat(timespec="seconds")
                alerts.append({
                    "key": key, "icon": "🔴", "symbol": sym,
                    "text": (f"🔴 <b>NSE:{sym}</b> CAR flipped NEGATIVE → "
                             f"<b>Avoid Hold</b> — delete any pending GTT"),
                })

    # --- 5) daily move alerts ------------------------------------------------
    if want_move:
        for sym, rows in prices.items():
            if len(rows) < 2:
                continue
            close, prev_close, d = latest_and_prev_closes(rows)
            if not prev_close:
                continue
            pct = (close - prev_close) / prev_close * 100
            if abs(pct) < move_pct:
                continue
            key = f"move:{sym}:{d}"
            if key in sent:
                continue
            sent[key] = now.isoformat(timespec="seconds")
            arrow = "📈" if pct > 0 else "📉"
            alerts.append({
                "key": key, "icon": arrow, "symbol": sym,
                "text": (f"{arrow} <b>NSE:{sym}</b> {pct:+.1f}% "
                         f"({prev_close:.2f} → {close:.2f})"),
            })

    # --- 6) persist state / baseline ----------------------------------------
    state["positives"] = sorted(positives)
    state["sent"] = sent
    _prune_sent(state)
    persisted = False
    if not dry_run:
        save_state(state_file, state)
        persisted = True

    # --- 7) send -------------------------------------------------------------
    message = ""
    if alerts:
        message = format_alerts_message(alerts, now, baseline=baseline)
        if send and not dry_run:
            _token, _chat, _thread = cfg.telegram_credentials(require=True)
            send_text(message, token=_token, chat_id=_chat, thread_id=_thread)
        elif dry_run:
            print("-" * 60)
            print(f"[DRY RUN] would send {len(alerts)} alert(s):")
            print(message)
            print("-" * 60)
        else:
            print(message)
    else:
        print("ℹ️  No new alerts.")

    return {"alerts": alerts, "count": len(alerts), "baseline": baseline,
            "positives": sorted(positives), "state_saved": persisted,
            "message": message}


def format_alerts_message(alerts: list[dict], now: datetime, baseline: bool = False) -> str:
    head = (f"🚨 <b>Market Alerts</b> — {now.strftime('%a %d %b %Y, %H:%M')} IST"
            if not baseline else
            f"🚨 <b>Market Alerts</b> — {now.strftime('%a %d %b %Y, %H:%M')} IST\n"
            f"ℹ️ First run: baseline saved ({len(alerts)} event(s))")
    body = "\n".join(a["text"] for a in alerts)
    return (f"{head}\n\n{body}\n\n"
            f"<i>Educational only — not investment advice.</i>")
