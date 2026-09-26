"""Configuration loading: config.json + environment variable overrides."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"


def load_config(path: str | os.PathLike | None = None) -> dict:
    """Load config.json (path may be overridden by CONFIG_FILE env var)."""
    cfg_path = Path(path or os.environ.get("CONFIG_FILE") or DEFAULT_CONFIG)
    if not cfg_path.exists():
        sys.exit(f"❌ Config file not found: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def monitor_repo(config: dict, override: str | None = None) -> str:
    """
    Resolve which repository to watch. Priority:
    CLI --repo  >  MONITOR_REPO env  >  config.monitor_repo  >  error.
    """
    repo = (override
            or os.environ.get("MONITOR_REPO")
            or config.get("monitor_repo")
            or "").strip()
    if not repo:
        sys.exit("❌ No repository to watch. Set monitor_repo in config.json "
                 "or pass --repo owner/name (or the MONITOR_REPO env var).")
    if repo.count("/") != 1:
        sys.exit(f"❌ Invalid repository '{repo}' — expected owner/name.")
    return repo


def telegram_credentials(require: bool = True) -> tuple[str, str, str | None]:
    """Return (bot_token, chat_id, message_thread_id)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    thread_id = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "").strip() or None
    if require and (not token or not chat_id):
        sys.exit("❌ TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment "
                 "variables are required (see README.md, step: credentials).")
    return token, chat_id, thread_id


def github_token() -> str | None:
    """Optional GitHub token (raises API rate limits when present)."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def env_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes", "on"}
