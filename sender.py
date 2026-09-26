"""
sender.py — Deliver a message to Telegram via the Bot API (pure stdlib).

Safety features:
  * Splits long messages at line boundaries so HTML tags are never cut
    (Telegram hard limit: 4096 chars per message).
  * Retries on 429 / 5xx with server-suggested delay and exponential backoff.
  * Falls back to plain text if Telegram rejects the HTML.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TELEGRAM_LIMIT = 4096
MAX_RETRIES = 4
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_tags(text: str) -> str:
    return html.unescape(TAG_RE.sub("", text))


def pack_lines(lines: list[str]) -> list[str]:
    """Group whole lines into chunks of at most TELEGRAM_LIMIT chars."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if len(line) > TELEGRAM_LIMIT - 1:          # never split a line mid-way
            line = line[: TELEGRAM_LIMIT - 4] + " …"
        extra = len(line) + (1 if current else 0)
        if current and size + extra > TELEGRAM_LIMIT:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += extra
    if current:
        chunks.append("\n".join(current))
    return chunks


def _api_call(method: str, payload: dict, token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return body
            description = str(body.get("description", ""))
            if "429" in description or "Too Many Requests" in description:
                raise urllib.error.HTTPError(url, 429, description, {}, None)
            return body  # logical error (bad chat id, ...) -> do not retry
        except urllib.error.HTTPError as exc:
            last_error = exc
            retry_after = None
            try:
                retry_after = exc.headers.get("retry-after") if exc.headers else None
            except Exception:
                retry_after = None
            if not retry_after and exc.code == 429:
                match = re.search(r"retry after (\d+)", str(exc.reason or ""))
                if match:
                    retry_after = match.group(1)
            if exc.code == 429 or 500 <= exc.code < 600 or "Too Many Requests" in str(exc.reason):
                delay = int(retry_after) if retry_after else min(2 ** attempt * 2, 30)
                print(f"⚠️  Telegram busy/HTTP {exc.code}, retry {attempt}/{MAX_RETRIES} "
                      f"in {delay}s …", flush=True)
                time.sleep(delay)
                continue
            raise
        except Exception as exc:  # network hiccup
            last_error = exc
            delay = min(2 ** attempt * 2, 30)
            print(f"⚠️  {type(exc).__name__}: {exc} — retry {attempt}/{MAX_RETRIES} "
                  f"in {delay}s …", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"Telegram API failed after {MAX_RETRIES} retries: {last_error}")


def send_text(text: str, *, token: str, chat_id: str, thread_id: str | None = None,
              dry_run: bool = False) -> int:
    """
    Send `text` (HTML allowed) to Telegram, chunking as needed.
    Returns the number of message chunks sent (0 if text is empty).
    """
    content = (text or "").strip()
    if not content:
        print("ℹ️  Nothing to send (empty message).", flush=True)
        return 0

    chunks = pack_lines(content.splitlines())
    sent = 0
    for i, chunk in enumerate(chunks, 1):
        payload: dict = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if thread_id:
            payload["message_thread_id"] = thread_id

        if dry_run:
            bar = "-" * 60
            print(f"{bar}\n[DRY RUN] chunk {i}/{len(chunks)} · {len(chunk)} chars "
                  f"-> chat {chat_id or '(dry-run)'}\n{chunk}\n{bar}", flush=True)
            sent += 1
            continue

        body = _api_call("sendMessage", payload, token)
        if body.get("ok"):
            print(f"✅ Sent chunk {i}/{len(chunks)} ({len(chunk)} chars) to chat {chat_id}",
                  flush=True)
            sent += 1
        else:
            description = str(body.get("description", ""))
            if "parse" in description.lower() or "entity" in description.lower():
                print(f"⚠️  HTML rejected ({description}); resending as plain text …", flush=True)
                payload["text"] = strip_tags(chunk)
                payload.pop("parse_mode", None)
                body = _api_call("sendMessage", payload, token)
                if body.get("ok"):
                    print(f"✅ Sent chunk {i}/{len(chunks)} ({len(payload['text'])} chars, "
                          f"plain) to chat {chat_id}", flush=True)
                    sent += 1
                    continue
            raise RuntimeError(f"Telegram send failed: {body.get('description', body)} "
                               f"(error_code={body.get('error_code')})")
        if i < len(chunks) and not dry_run:
            time.sleep(0.5)  # gentle pacing between messages
    return sent
