"""
scheduler.py — A tiny built-in Python scheduler (no cron, no GitHub Actions).

Supports:
  mode "daily"    -> fire once every day at HH:MM in the configured timezone
  mode "interval" -> fire every N hours

Uses zoneinfo (stdlib) so the schedule is correct in your local timezone
(default: Asia/Kolkata — IST, no DST).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

POLL_SECONDS = 20  # check the clock every 20s so Ctrl-C stays responsive


def get_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Unknown timezone '{name}' — use e.g. Asia/Kolkata, UTC") from exc


def next_fire_time(now: datetime, *, mode: str, at: str = "09:00",
                   every_hours: int = 24, tz: str = "Asia/Kolkata") -> datetime:
    """Compute the next fire time as an aware datetime in `tz`."""
    zone = get_tz(tz)
    now = now.astimezone(zone)

    if mode == "interval":
        return now + timedelta(hours=max(1, int(every_hours)))

    if mode != "daily":
        raise ValueError(f"Unknown schedule mode '{mode}' (use 'daily' or 'interval')")

    try:
        hour_s, minute_s = at.split(":")
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"Invalid schedule time '{at}' — expected HH:MM (24h)") from exc

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def seconds_until(target: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(target.tzinfo)
    return max(0.0, (target - now).total_seconds())


def run_forever(job: Callable[[], None], schedule_cfg: dict) -> None:
    """
    Run `job()` on the configured schedule until interrupted (Ctrl-C).
    job() exceptions are logged and do not kill the scheduler.
    """
    mode = schedule_cfg.get("mode", "daily")
    at = schedule_cfg.get("time", "09:00")
    every_hours = int(schedule_cfg.get("every_hours", 24))
    tz = schedule_cfg.get("timezone", "Asia/Kolkata")

    print(f"📅 Scheduler started — mode={mode}"
          + (f", daily at {at} {tz}" if mode == "daily" else f", every {every_hours}h")
          + ". Press Ctrl-C to stop.", flush=True)

    while True:
        target = next_fire_time(datetime.now(get_tz(tz)), mode=mode, at=at,
                                every_hours=every_hours, tz=tz)
        print(f"💤 Next run: {target.isoformat()} "
              f"(in {timedelta(seconds=int(seconds_until(target)))})", flush=True)

        while True:
            remaining = seconds_until(target)
            if remaining <= 0:
                break
            time.sleep(min(POLL_SECONDS, remaining))

        print(f"🔔 Fired at {datetime.now(get_tz(tz)).isoformat()} — running job …", flush=True)
        try:
            job()
            print("✅ Job finished successfully.", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # keep the scheduler alive
            print(f"❌ Job failed: {type(exc).__name__}: {exc}", flush=True)
        # small settle delay so we don't double-fire within the same minute
        time.sleep(2)
