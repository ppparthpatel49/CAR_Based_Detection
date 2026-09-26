"""
__main__.py — Command line interface.

Usage (from the repository root):
    python -m telegram_repo_alerts run-once     # collect + send once
    python -m telegram_repo_alerts schedule     # run forever on a Python schedule
    python -m telegram_repo_alerts fetch        # only build digest.txt
    python -m telegram_repo_alerts send         # only send existing digest.txt
    python -m telegram_repo_alerts test         # send a ping to verify the bot
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, config as cfg
from .collector import build_digest
from .scheduler import get_tz, run_forever
from .sender import send_text

DEFAULT_DIGEST = os.environ.get("DIGEST_FILE", "digest.txt")


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def cmd_fetch(args) -> int:
    """Build the digest file without sending."""
    config = cfg.load_config(args.config)
    repo = cfg.monitor_repo(config, args.repo)
    text = build_digest(repo, config=config, lookback_hours=args.lookback)
    _write(args.output, text)
    if text:
        print(f"📥 Digest for {repo} -> {args.output} ({len(text)} chars)")
    else:
        print(f"ℹ️  No activity for {repo} in the window; {args.output} left empty.")
    return 0


def cmd_send(args) -> int:
    """Send an existing digest file to Telegram."""
    dry = args.dry_run or cfg.env_dry_run()
    token, chat_id, thread_id = cfg.telegram_credentials(require=not dry)
    text = _read(args.input)
    sent = send_text(text, token=token, chat_id=chat_id, thread_id=thread_id, dry_run=dry)
    if sent:
        print(f"🎉 Delivered {sent} message chunk(s).")
    return 0


def cmd_run_once(args) -> int:
    """Collect events and send the digest — one shot (ideal for cron)."""
    dry = args.dry_run or cfg.env_dry_run()
    config = cfg.load_config(args.config)
    repo = cfg.monitor_repo(config, args.repo)
    lookback = args.lookback or config.get("lookback_hours")

    print(f"🔎 Collecting events for {repo} (last {lookback}h) …")
    text = build_digest(repo, config=config, lookback_hours=args.lookback)
    out_file = getattr(args, "output", None) or os.environ.get("DIGEST_FILE")
    if out_file:
        _write(out_file, text)
        print(f"   saved copy -> {out_file}")

    if not text:
        print("ℹ️  Nothing to send (and empty-note disabled in config).")
        return 0

    token, chat_id, thread_id = cfg.telegram_credentials(require=not dry)
    sent = send_text(text, token=token, chat_id=chat_id, thread_id=thread_id, dry_run=dry)
    print(f"🎉 Done — {sent} chunk(s) delivered to Telegram.")
    return 0


def cmd_schedule(args) -> int:
    """Run forever: fire the job on the Python schedule defined in config.json."""
    dry = args.dry_run or cfg.env_dry_run()
    config = cfg.load_config(args.config)
    # fail fast on missing credentials instead of at 9 a.m. tomorrow
    cfg.telegram_credentials(require=not dry)
    cfg.monitor_repo(config, args.repo)

    def job() -> None:
        cmd_run_once(args)

    try:
        run_forever(job, config.get("schedule", {}))
    except KeyboardInterrupt:
        print("\n👋 Scheduler stopped by user.")
    return 0


def cmd_lists(args) -> int:
    """Show/validate the two stock-list CSV files."""
    from .market_data import list_summary

    config = cfg.load_config(args.config)
    print("📋 Stock lists:")
    for entry in list_summary(config):
        status = f"{entry['count']} symbols" if entry["count"] else "⚠️ unavailable"
        print(f"  • {entry['name']:<12} {status:<16} {entry['path']}")
        if entry["count"]:
            print(f"      sample: {entry['sample']} …")
    return 0


def cmd_download(args) -> int:
    """Download Nifty 100 / custom stock-list price history via yfinance."""
    from .market_data import download_history, resolve_lists

    config = cfg.load_config(args.config)
    data_cfg = config.get("data", {})
    which = args.list or data_cfg.get("source", "both")

    lists = resolve_lists(config, which)
    if not lists:
        print("❌ No stock lists to download from.")
        return 1

    # Merge all selected lists into ONE download (dedup keeps a symbol that
    # appears in both lists from being fetched/written twice).
    merged: list[str] = []
    seen: set[str] = set()
    membership: dict[str, list[str]] = {}  # symbol -> [list names]
    for name, symbols in lists:
        fresh = 0
        for sym in symbols:
            membership.setdefault(sym, []).append(name)
            if sym not in seen:
                seen.add(sym)
                merged.append(sym)
                fresh += 1
        print(f"📦 List: {name} — {len(symbols)} symbols ({fresh} new)")
    if len(merged) < sum(len(s) for _, s in lists):
        print(f"   🔀 after de-duplication: {len(merged)} unique symbols")

    summary = download_history(
        merged,
        period=args.period or data_cfg.get("period", "2y"),
        interval=args.interval or data_cfg.get("interval", "1d"),
        suffix=data_cfg.get("suffix", ".NS"),
        output_dir=data_cfg.get("output_dir", "data/prices"),
    )
    print(f"\n   ✅ {summary['downloaded']} downloaded · "
          f"❌ {len(summary['failed'])} failed · rows={summary['rows']}")
    for f in summary["files"]:
        print(f"   📄 {f}")

    # per-list breakdown of failures
    failed = summary["failed"]
    if failed:
        for name, symbols in lists:
            hits = [s for s in symbols if s in set(failed)]
            if hits:
                shown = ", ".join(hits[:10])
                more = f" … (+{len(hits) - 10})" if len(hits) > 10 else ""
                print(f"   ⚠️  {name} failures: {shown}{more}")

    print(f"\n🎉 Download finished. Total failures: {len(failed)}")
    # non-zero exit when nothing at all could be downloaded (bad period,
    # no network, wrong suffix, ...) so schedulers/cron can alert on it
    if summary["downloaded"] == 0 and merged:
        print("❌ No symbols downloaded successfully.", file=sys.stderr)
        return 2
    return 0


def cmd_report(args) -> int:
    """Weekly CAR report: console + append-only log file + optional Telegram."""
    from . import car
    from .sender import send_text

    config = cfg.load_config(args.config)
    rep_cfg = config.get("report", {})
    prices = args.prices or rep_cfg.get("prices", "data/prices/prices_daily.csv")
    prices_path = Path(prices) if os.path.isabs(prices) else Path(__file__).resolve().parent.parent / prices
    log_path = args.log or rep_cfg.get("log", "logs/car_log.csv")
    dry = args.dry_run or cfg.env_dry_run()

    report = car.run_analysis(prices_path,
                              car_days=args.car_days or rep_cfg.get("car_days", 10),
                              week_start=args.week_start)
    print(car.console_report(report))

    # --- 1) store in the repo's log file ---------------------------------
    logged = 0
    if not args.no_log:
        logged = car.append_log(report, log_path, log_all=args.log_all)
        print(f"📄 Logged {logged} row(s) -> {log_path}")

    # --- 2) full CSV dump (optional) -------------------------------------
    if args.csv:
        import csv as _csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(report["results"][0].keys()))
            w.writeheader()
            w.writerows(report["results"])
        print(f"📄 Full results ({report['scanned']} rows) -> {args.csv}")

    # --- 3) Telegram message ---------------------------------------------
    wants_send = args.telegram or rep_cfg.get("send_telegram", False)
    if wants_send:
        message = car.format_message(report, log_note=f"logged to {log_path}" if logged else "")
        if args.message_out:
            Path(args.message_out).write_text(message, encoding="utf-8")
            print(f"📄 Telegram message saved -> {args.message_out}")
        token, chat_id, thread_id = cfg.telegram_credentials(require=not dry)
        send_text(message, token=token, chat_id=chat_id, thread_id=thread_id, dry_run=dry)
    return 0


def cmd_alerts(args) -> int:
    """Detect market alerts (GTT cross / CAR flip / big move) → Telegram."""
    from .alerts import check_alerts

    config = cfg.load_config(args.config)
    alert_cfg = config.get("alerts", {})
    if not alert_cfg.get("enabled", True):
        print("ℹ️  alerts.enabled = false in config.json — nothing to do.")
        return 0
    dry = args.dry_run or cfg.env_dry_run()
    send = (not args.no_send) and bool(alert_cfg.get("send_telegram", True))
    summary = False if args.no_summary else None  # None → use config default

    summary_r = check_alerts(
        config,
        refresh=not args.no_refresh,
        dry_run=dry,
        send=send,
        threshold=args.threshold,
        force=args.force,
        summary=summary,
    )

    # --- clear diagnostics: say exactly what happened and why ---------------
    n, filtered = summary_r["count"], summary_r["filtered"]
    print(f"🔎 {n} new event(s) detected" +
          (f" · {filtered} already sent earlier (use --force to resend)" if filtered else ""))
    if dry:
        state_note = "state NOT written (dry-run)"
        send_note = "would send (dry-run)" if summary_r["message"] else \
            (summary_r.get("skip_reason") or "nothing to send")
    elif summary_r["message_sent"]:
        state_note = "state saved"
        send_note = f"✅ Telegram {summary_r['msg_kind']} message SENT"
    elif summary_r["message"] and not send:
        state_note = "state saved (no-send mode)"
        send_note = "⏭️ Telegram skipped (--no-send / send_telegram=false)"
    elif summary_r["message"]:
        state_note = "state saved"
        send_note = "✅ sent"
    else:
        state_note = "state saved"
        send_note = f"ℹ️ {summary_r.get('skip_reason') or 'nothing to send'}"
    print(f"📨 Telegram: {send_note} · {state_note}")
    return 0


def cmd_test(args) -> int:
    """Send a small ping message to verify bot token + chat id."""
    dry = args.dry_run or cfg.env_dry_run()
    token, chat_id, thread_id = cfg.telegram_credentials(require=not dry)
    tz = get_tz(cfg.load_config(args.config).get("schedule", {}).get("timezone", "Asia/Kolkata"))
    text = ("✅ <b>telegram-repo-alerts</b> test message\n"
            f"🕐 {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            "🎉 Your Telegram automation is working!")
    send_text(text, token=token, chat_id=chat_id, thread_id=thread_id, dry_run=dry)
    return 0


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m telegram_repo_alerts",
        description="Pure-Python automation: GitHub repo events -> Telegram digest.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, digest_out: bool = False) -> None:
        p.add_argument("--repo", help="watch owner/name (overrides config/monitor_repo)")
        p.add_argument("--config", help="path to config.json")
        p.add_argument("--lookback", type=int, metavar="HOURS",
                       help="how many hours of activity to include")
        p.add_argument("--dry-run", action="store_true",
                       help="print the Telegram payload instead of sending")
        if digest_out:
            p.add_argument("-o", "--output", default=DEFAULT_DIGEST,
                           help=f"digest output file (default: {DEFAULT_DIGEST})")

    p_fetch = sub.add_parser("fetch", help="only build the digest file (no Telegram)")
    common(p_fetch, digest_out=True)
    p_fetch.set_defaults(func=cmd_fetch)

    p_send = sub.add_parser("send", help="only send an existing digest file")
    p_send.add_argument("-i", "--input", default=DEFAULT_DIGEST,
                        help=f"digest file to send (default: {DEFAULT_DIGEST})")
    p_send.add_argument("--dry-run", action="store_true", help="print instead of sending")
    p_send.set_defaults(func=cmd_send)

    p_once = sub.add_parser("run-once", help="collect + send once (for cron/systemd timers)")
    common(p_once, digest_out=True)
    p_once.set_defaults(func=cmd_run_once)

    p_sched = sub.add_parser("schedule", help="run forever on the configured schedule")
    common(p_sched)
    p_sched.set_defaults(func=cmd_schedule)

    p_lists = sub.add_parser("lists", help="show/validate nifty_100.csv and stock_list.csv")
    p_lists.add_argument("--config", help="path to config.json")
    p_lists.set_defaults(func=cmd_lists)

    p_dl = sub.add_parser("download",
                          help="download price history for the CSV lists via yfinance")
    p_dl.add_argument("--config", help="path to config.json")
    p_dl.add_argument("--list", choices=["nifty", "custom", "both"],
                      help="which list(s) to download (default: data.source in config)")
    p_dl.add_argument("--period", help="yfinance period, e.g. 6mo, 1y, 2y, 5y, max")
    p_dl.add_argument("--interval", help="yfinance interval, e.g. 1d, 1wk")
    p_dl.set_defaults(func=cmd_download)

    p_rep = sub.add_parser("report",
                           help="weekly CAR report: console + logs/car_log.csv + Telegram")
    p_rep.add_argument("--config", help="path to config.json")
    p_rep.add_argument("--prices", help="prices CSV (default: data/prices/prices_daily.csv)")
    p_rep.add_argument("--car-days", type=int, help="streak needed for Buy/Average Out (video: 10)")
    p_rep.add_argument("--week-start", help="YYYY-MM-DD (default: Monday of latest week)")
    p_rep.add_argument("--log", help="log CSV path (default: logs/car_log.csv)")
    p_rep.add_argument("--log-all", action="store_true",
                       help="log all stocks, not only CAR-positive ones")
    p_rep.add_argument("--no-log", action="store_true", help="skip writing the log file")
    p_rep.add_argument("--csv", help="also dump full per-stock results to this CSV")
    p_rep.add_argument("--telegram", action="store_true",
                       help="send the report as a Telegram message")
    p_rep.add_argument("--message-out", help="save the Telegram HTML message to a file")
    p_rep.add_argument("--dry-run", action="store_true",
                       help="print the Telegram message instead of sending")
    p_rep.set_defaults(func=cmd_report)

    p_al = sub.add_parser("alerts",
                          help="market alerts: GTT trigger crossed / CAR flip / big move")
    p_al.add_argument("--config", help="path to config.json")
    p_al.add_argument("--no-refresh", action="store_true",
                      help="use existing prices file (skip yfinance download)")
    p_al.add_argument("--no-send", action="store_true",
                      help="update de-dup state but do not call Telegram")
    p_al.add_argument("--threshold", type=float,
                      help="override daily_move_pct (e.g. 2.5; 0 disables)")
    p_al.add_argument("--force", action="store_true",
                      help="ignore de-dup state and (re)send everything detected")
    p_al.add_argument("--no-summary", action="store_true",
                      help="do not send the daily summary on quiet days")
    p_al.add_argument("--dry-run", action="store_true",
                      help="print alerts; no Telegram call, no state write")
    p_al.set_defaults(func=cmd_alerts)

    p_test = sub.add_parser("test", help="send a ping to verify Telegram credentials")
    p_test.add_argument("--config", help="path to config.json")
    p_test.add_argument("--dry-run", action="store_true", help="print instead of sending")
    p_test.set_defaults(func=cmd_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n👋 Interrupted.")
        return 130
    except Exception as exc:  # pragma: no cover
        print(f"❌ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
