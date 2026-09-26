"""
collector.py — Fetch recent GitHub repository events and build a
Telegram-friendly HTML digest (pure stdlib: urllib + json + html).
"""
from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config as cfg

API_ROOT = "https://api.github.com"
MAX_PAGES = 3            # up to 300 events — plenty for any lookback window
PER_PAGE = 100


# --------------------------------------------------------------------------- utils
def esc(text) -> str:
    return html.escape(str(text), quote=False)


def one_line(text, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def gh_get(url: str, token: str | None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "telegram-repo-alerts (pure-python)",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {body}") from exc


def fetch_events(repo: str, token: str | None) -> list[dict]:
    fixture = os.environ.get("EVENTS_FILE")  # offline testing hook
    if fixture:
        with open(fixture, "r", encoding="utf-8") as fh:
            return json.load(fh)
    events: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{API_ROOT}/repos/{repo}/events?per_page={PER_PAGE}&page={page}"
        batch = gh_get(url, token)
        if not batch:
            break
        events.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return events


def fetch_repo_meta(repo: str, token: str | None) -> dict:
    if os.environ.get("EVENTS_FILE"):
        return {"full_name": repo, "stargazers_count": 0}
    try:
        return gh_get(f"{API_ROOT}/repos/{repo}", token)
    except RuntimeError:
        return {"full_name": repo}


# ----------------------------------------------------------------- event formatting
def fmt_push(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    ref = (p.get("ref") or "").replace("refs/heads/", "")
    commits = p.get("commits") or []
    size = p.get("size", len(commits))
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    lines = [f"🔀 <b>Push</b> · <code>{esc(ref or '?')}</code> · {size} commit(s) · by <b>{actor}</b>"]
    for c in commits[:5]:
        sha = (c.get("sha") or "")[:7]
        lines.append(f"   • <code>{esc(sha)}</code> {esc(one_line(c.get('message', ''), 80))}")
    if len(commits) > 5:
        lines.append(f"   … +{len(commits) - 5} more commit(s)")
    return lines


def fmt_issue(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    action = p.get("action", "updated")
    issue = p.get("issue", {})
    icon = {"opened": "🆕", "closed": "✅", "reopened": "🔁"}.get(action, "📌")
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    return [
        f"{icon} <b>Issue #{issue.get('number', '?')}</b> {esc(action)} by <b>{actor}</b>\n"
        f"   {esc(one_line(issue.get('title', ''), 100))}"
    ]


def fmt_pr(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    action = p.get("action", "updated")
    pr = p.get("pull_request", {})
    if action == "closed" and pr.get("merged"):
        action = "merged"
    icon = {"opened": "🟢", "closed": "🟡", "merged": "🟣", "reopened": "🔁"}.get(action, "🔵")
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    title = one_line(pr.get("title") or "", 100)
    line = f"{icon} <b>PR #{pr.get('number', '?')}</b> {esc(action)} by <b>{actor}</b>"
    if title:
        line += f"\n   {esc(title)}"
    return [line]


def fmt_star(ev: dict) -> list[str]:
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    return [f"⭐ <b>Starred</b> by <b>{actor}</b>"]


def fmt_fork(ev: dict) -> list[str]:
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    target = esc((ev.get("payload", {}).get("forkee") or {}).get("full_name", "?"))
    return [f"🍴 <b>Forked</b> to <code>{target}</code> by <b>{actor}</b>"]


def fmt_release(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    rel = p.get("release", {})
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    tag = esc(rel.get("tag_name", "?"))
    name = one_line(rel.get("name") or rel.get("tag_name", ""), 70)
    line = f"🎁 <b>Release {tag}</b> ({esc(p.get('action', 'published'))}) by <b>{actor}</b>"
    if name:
        line += f"\n   {esc(name)}"
    return [line]


def fmt_create(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    ref_type = p.get("ref_type", "ref")
    ref = p.get("ref") or p.get("description") or "(repo)"
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    return [f"🆕 <b>Created {esc(ref_type)}</b> <code>{esc(ref)}</code> by <b>{actor}</b>"]


def fmt_delete(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    return [f"🗑️ <b>Deleted {esc(p.get('ref_type', 'ref'))}</b> "
            f"<code>{esc(p.get('ref', '?'))}</code> by <b>{actor}</b>"]


def fmt_comment(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    if "issue" in p:
        return [f"💬 <b>Comment</b> on issue #{p['issue'].get('number', '?')} by <b>{actor}</b>"]
    sha = (p.get("commit_id") or "")[:7]
    return [f"💬 <b>Comment</b> on commit <code>{esc(sha)}</code> by <b>{actor}</b>"]


def fmt_review(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    pr = p.get("pull_request", {})
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    return [f"👀 <b>Review {esc(p.get('action', 'commented'))}</b> "
            f"on PR #{pr.get('number', '?')} by <b>{actor}</b>"]


def fmt_member(ev: dict) -> list[str]:
    p = ev.get("payload", {})
    actor = esc((ev.get("actor") or {}).get("login", "?"))
    member = esc((p.get("member") or {}).get("login", "?"))
    return [f"🤝 <b>Collaborator added</b>: {member} by <b>{actor}</b>"]


def fmt_public(_ev: dict) -> list[str]:
    return ["🌍 <b>Repository made public</b>"]


# GitHub event type -> (config key, count icon, formatter)
HANDLERS: dict[str, tuple[str, str, object]] = {
    "PushEvent":              ("push",         "🔀", fmt_push),
    "IssuesEvent":            ("issues",       "🆕", fmt_issue),
    "PullRequestEvent":       ("pull_request", "🔵", fmt_pr),
    "WatchEvent":             ("star",         "⭐", fmt_star),
    "ForkEvent":              ("fork",         "🍴", fmt_fork),
    "ReleaseEvent":           ("release",      "🎁", fmt_release),
    "CreateEvent":            ("create",       "🆕", fmt_create),
    "DeleteEvent":            ("delete",       "🗑️", fmt_delete),
    "IssueCommentEvent":      ("comment",      "💬", fmt_comment),
    "CommitCommentEvent":     ("comment",      "💬", fmt_comment),
    "PullRequestReviewEvent": ("review",       "👀", fmt_review),
    "MemberEvent":            ("member",       "🤝", fmt_member),
    "PublicEvent":            ("public",       "🌍", fmt_public),
}


# --------------------------------------------------------------------------- main
def build_digest(repo: str, *, config: dict | None = None,
                 lookback_hours: int | None = None, token: str | None = None) -> str:
    """
    Collect events for `repo` and return the digest text.

    Returns "" when there is nothing to report and the config disables
    the 'empty note' message.
    """
    config = config if config is not None else cfg.load_config()
    lookback = int(lookback_hours
                   or os.environ.get("LOOKBACK_HOURS")
                   or config.get("lookback_hours", 24))
    enabled = set(config.get("enabled_events", []))
    max_events = int(config.get("max_events", 120))
    msg_cfg = config.get("message", {})
    header = msg_cfg.get("header", "📦 <b>GitHub Repo Digest</b>")
    show_empty = bool(msg_cfg.get("show_empty_note", True))
    empty_note = msg_cfg.get("empty_note", "✅ No new activity in this window.")
    footer = msg_cfg.get("footer", "")
    token = token if token is not None else cfg.github_token()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)
    raw = fetch_events(repo, token)

    kept: list[dict] = []
    for ev in raw:
        handler = HANDLERS.get(ev.get("type", ""))
        if not handler:
            continue
        key, _, _ = handler
        if enabled and key not in enabled:
            continue
        try:
            created = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            continue
        if created >= cutoff:
            kept.append(ev)
    kept = kept[:max_events]

    # --- nothing new ----------------------------------------------------
    if not kept:
        if not show_empty:
            return ""
        body = [header,
                f"📁 <code>{esc(repo)}</code> · 🕐 last {lookback}h",
                "", empty_note]
        if footer:
            body += ["", footer]
        return "\n".join(body)

    # --- build digest ---------------------------------------------------
    counts: dict[str, int] = {}
    icon_by_key: dict[str, str] = {}
    blocks: list[str] = []
    for ev in kept:
        key, icon, fmt = HANDLERS[ev["type"]]
        icon_by_key.setdefault(key, icon)
        counts[key] = counts.get(key, 0) + 1
        blocks.extend(fmt(ev))

    meta = fetch_repo_meta(repo, token)
    stars = meta.get("stargazers_count")
    parts = [f"{icon_by_key.get(k, '•')} {v} {k.replace('_', ' ')}" for k, v in counts.items()]

    lines = [
        header,
        f"📁 <code>{esc(repo)}</code> · 🕐 last {lookback}h · "
        f"<b>{len(kept)}</b> event(s)" + (f" · ⭐ {stars}" if isinstance(stars, int) else ""),
        "  " + " · ".join(parts),
        "",
        *blocks,
    ]
    if len(kept) >= max_events:
        lines += ["", f"… list truncated at {max_events} events"]
    if footer:
        lines += ["", footer]
    return "\n".join(lines)
