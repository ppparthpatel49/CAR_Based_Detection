"""
telegram_repo_alerts — a fully Python-based automation that watches a GitHub
repository for activity (pushes, issues, PRs, stars, releases, ...) and
automatically sends a formatted digest message to Telegram on a schedule.

No GitHub Actions, no external scheduler, no third-party dependencies —
everything (scheduling + collection + delivery) is plain Python.
"""

__version__ = "1.0.0"
__all__ = ["config", "collector", "sender", "scheduler"]
