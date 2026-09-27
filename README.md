# 📲 telegram-repo-alerts — 100% Python

A **fully Python-based automation** — the core runs anywhere Python runs: no server,
no cron required (though both work). One Python program does **everything**:

1. ⏰ **Schedules itself** (built-in Python scheduler: daily at a chosen time, or every N hours)
2. 🔎 **Collects GitHub repository events** (pushes, issues, PRs, stars, releases, forks, comments…)
3. ✈️ **Formats & automatically sends a Telegram message** (HTML, auto-chunked under 4096 chars)
4. 📈 **Downloads NSE market data with yfinance** for two swappable CSV stock lists
   (`data/nifty_100.csv` — replace every 6 months · `data/stock_list.csv` — your custom list)
5. 🚨 **Instant market alerts to Telegram** — GTT trigger crossed, CAR status flips,
   ±3% daily moves — with de-duplication; optionally run on a free
   **GitHub Actions cron** (the only workflow file in the repo, purely a trigger —
   all logic stays Python)

**Almost pure standard library** — the only third-party package is `yfinance` (market data).

```
┌──────────────────────────────────────────────────────────────┐
│                  python -m telegram_repo_alerts             │
│                                                              │
│  scheduler.py  ──fires──►  collector.py  ──digest──► sender  │
│  (daily 09:00     (GitHub Events API)         (Telegram Bot  │
│   Asia/Kolkata)                              API, retries)   │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository layout (entirely Python)

```
telegram-repo-alerts/
├── .github/workflows/
│   └── market-alerts.yml          ← ⏰ free cron runner: fires `alerts` daily after 5 PM IST
├── telegram_repo_alerts/          ← the whole application (Python package)
│   ├── __init__.py
│   ├── __main__.py                ← CLI: run-once/schedule/fetch/send/download/lists/report/alerts/test
│   ├── config.py                  ← config.json + env var handling
│   ├── collector.py               ← GitHub Events API → HTML digest
│   ├── sender.py                  ← Telegram Bot API delivery (chunking + retries)
│   ├── scheduler.py               ← built-in daily/interval scheduler (zoneinfo)
│   ├── market_data.py             ← yfinance downloader + flexible CSV list loader
│   ├── car.py                     ← weekly CAR report engine (log + Telegram)
│   └── alerts.py                  ← 🚨 market alert engine (GTT/CAR/moves + de-dup state)
├── data/
│   ├── nifty_100.csv              ← 📝 REPLACE every 6 months (NSE constituents file)
│   ├── stock_list.csv             ← 📝 YOUR custom stock list (edit/upload any time)
│   └── prices/                    ← ⬇️ downloaded data (git-ignored, regenerate anytime)
│       ├── prices_daily.csv           symbol,date,open,high,low,close,volume
│       └── latest_prices.csv          symbol,date,close
├── logs/
│   ├── car_log.csv                ← 📜 append-only history of weekly CAR results
│   └── alerts_state.json          ← 🛡️ alert de-dup state (auto-committed by Actions)
├── config.json                    ← repo, schedule, data lists, event filters
├── pyproject.toml                 ← installable package + `repo-alerts` command
├── requirements.txt               ← yfinance
├── README.md
├── LICENSE
└── .gitignore
```

---

## ⚡ Quick start

### 1. Install & get Telegram credentials (2 minutes)

```bash
cd telegram-repo-alerts
pip install -r requirements.txt     # installs yfinance (only third-party dep)
```

1. In Telegram, open **[@BotFather](https://t.me/BotFather)** → send `/newbot` → copy the
   **bot token** (`123456:AAE...xyz`).
2. Send any message to your new bot (or add it to a group/channel and post there).
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy
   `"chat":{"id": ...}` → that's your **chat id** (negative for groups/channels).

### 2. Configure

```bash
cd telegram-repo-alerts

# export your credentials (add to ~/.bashrc or ~/.zshrc to persist)
export TELEGRAM_BOT_TOKEN="123456:AAE...xyz"
export TELEGRAM_CHAT_ID="-1001234567890"
export GITHUB_TOKEN="ghp_..."        # optional: higher GitHub API rate limits
```

Edit `config.json`:

```jsonc
{
  "monitor_repo": "yourname/your-repo",   // ← the repo to watch (owner/name)
  "lookback_hours": 24,                   // window per message
  "schedule": {
    "mode": "daily",                      // "daily" | "interval"
    "time": "09:00",                      // daily fire time (24h)
    "timezone": "Asia/Kolkata"            // zoneinfo name; IST has no DST
  }
}
```

### 3. Verify & run

```bash
# send a ping to confirm token + chat id work
python -m telegram_repo_alerts test

# download Nifty 100 + custom list price history (yfinance)
python -m telegram_repo_alerts download

# build the digest and preview it in the terminal (no message sent)
python -m telegram_repo_alerts run-once --dry-run

# send one digest immediately
python -m telegram_repo_alerts run-once

# 🤖 start the always-on automation (fires every day at 09:00 IST)
python -m telegram_repo_alerts schedule
```

Expected output shape:

```
📥 Digest for yourname/your-repo -> digest.txt (1432 chars)
✅ Sent chunk 1/1 (1432 chars) to chat -1001234567890
🎉 Done — 1 chunk(s) delivered to Telegram.
```

---

## 🛠️ All commands

| Command | What it does |
|---|---|
| `python -m telegram_repo_alerts schedule` | Run forever; fire automatically per `config.json` |
| `python -m telegram_repo_alerts run-once` | Collect + send exactly once (ideal for cron/systemd) |
| `python -m telegram_repo_alerts fetch` | Only build `digest.txt` (no Telegram call) |
| `python -m telegram_repo_alerts send` | Only send an existing `digest.txt` |
| `python -m telegram_repo_alerts download` | ⬇️ Download price history for the CSV lists via **yfinance** |
| `python -m telegram_repo_alerts lists` | 📋 Show/validate `nifty_100.csv` and `stock_list.csv` |
| `python -m telegram_repo_alerts report` | 📈 Weekly **CAR report** → console + **`logs/car_log.csv`** + optional **Telegram** |
| `python -m telegram_repo_alerts alerts` | 🚨 **Market alerts** (GTT crossed · CAR flip · ±3% move) → Telegram, de-duplicated |
| `python -m telegram_repo_alerts test` | Ping message to verify credentials |

Common flags: `--repo owner/name` · `--lookback HOURS` · `--dry-run` · `--config path` · `-o file`
`download` flags: `--list nifty|custom|both` · `--period 6mo|1y|2y|5y|max` · `--interval 1d|1wk`
`report` flags: `--telegram` · `--log PATH` · `--log-all` · `--no-log` · `--csv PATH` · `--car-days 10` · `--message-out PATH`
`alerts` flags: `--force` (re-send everything) · `--no-summary` · `--no-refresh` · `--no-send` · `--threshold X` · `--dry-run`

Optional (after `pip install -e .`): the same CLI is available as **`repo-alerts`**.

---

## 📈 Market data (yfinance) — the two swappable CSV lists

The repo downloads **real NSE price history** with
[yfinance](https://github.com/ranaroussi/yfinance) (symbols get the `.NS` suffix
automatically, e.g. `RELIANCE` → `RELIANCE.NS`).

### 1️⃣ `data/nifty_100.csv` — the index list (replace every 6 months)

* Ships pre-filled with the **official Nifty 100 constituents** (downloaded from NSE's
  index file — columns: `Company Name, Industry, Symbol, Series, ISIN Code`).
* NSE reviews its indices **every 6 months (Jan 1 & Jul 1)** — simply download the fresh
  **"Nifty 100 constituents"** CSV from the Nifty/niftyindices website and **replace this
  file**. Any layout works as long as a `Symbol` column exists (or just one symbol per line).
* Loader tolerates: official NSE files, plain one-column lists, BOMs, quoted fields,
  `.NS` suffixes, duplicate rows.

### 2️⃣ `data/stock_list.csv` — your own custom list (upload any time)

```csv
Symbol,Name,Notes
RELIANCE,Reliance Industries,my core holding
TATASTEEL,Tata Steel,averaging candidate
```

Edit it whenever you like — extra columns (`Name`, `Notes`, …) are ignored by the
downloader; only `Symbol` matters. Same rules as above (header optional).

### ⬇️ Download

```bash
# default: both lists merged & de-duplicated (config data.source = "both")
python -m telegram_repo_alerts download

# only the index list, or only your custom list
python -m telegram_repo_alerts download --list nifty
python -m telegram_repo_alerts download --list custom --period 5y

# check which lists are loaded
python -m telegram_repo_alerts lists
```

Output (regenerated on every run, git-ignored):

| File | Columns |
|---|---|
| `data/prices/prices_daily.csv` | `symbol,date,open,high,low,close,volume` — full history, long format |
| `data/prices/latest_prices.csv` | `symbol,date,close` — latest trading-day snapshot |

Example (real run): `✅ 100 downloaded · ❌ 0 failed · rows=49355` for the Nifty 100 list
over `period=2y, interval=1d`.

> 💡 The long-format `prices_daily.csv` is exactly what you need to compute indicators
> such as the **CAR (Cumulative Average Reversal)** method — group by `symbol`, take the
> running average of `close` since each stock's 52-week high date.

---

## 📈 Weekly CAR report — log file + Telegram message

`report` applies the full method (CAR rating → `Buy/Average Out` / `Avoid Hold`,
200-DMA difference, week-high GTT triggers) and **stores the result two ways**:

```bash
# console + append to logs/car_log.csv  (every run is timestamped & appended)
python -m telegram_repo_alerts report

# ...and send it as a Telegram message too
python -m telegram_repo_alerts report --telegram

# preview the message without credentials
python -m telegram_repo_alerts report --telegram --dry-run --message-out msg.html

# extras
python -m telegram_repo_alerts report --log-all          # log all 100 stocks, not just positives
python -m telegram_repo_alerts report --csv full.csv     # full per-stock dump
```

**1️⃣ Log file — `logs/car_log.csv` (kept inside the repo):**

| column | example |
|---|---|
| `run_timestamp` | `2026-09-26 17:20:00` |
| `iso_week` / `week_start` / `week_end` | `2026-W39` / `2026-09-21` / `2026-09-25` |
| `nse_code` | `NSE:KOTAKBANK` |
| `cmp` / `diff_200dma_pct` | `404.0` / `1.05` |
| `car_rating` | `Buy/Average Out` |
| `gtt_trigger` / `gtt_limit` / `qty_5000` | `420.6` / `420.7` / `12` |
| `car_streak` / `year_high_date` / `year_high_close` | `23` / `2025-10-23` / `445.12` |
| `price_source` | `yfinance daily close` |

Each run **appends** (never overwrites), so the file becomes a week-over-week history
of every signal. By default only CAR-positive stocks are logged (`--log-all` for everything).

**2️⃣ Telegram message** (`--telegram`): a formatted table mirroring your sheet —
NSE Code · CMP · Difference from 200 DMA · CAR Rating · Trigger Price for GTT,
rows sorted by difference ascending — plus limit/qty per stock,
near-misses, log reference and disclaimer. Set `"send_telegram": true` under `report`
in `config.json` to send it automatically on every run (e.g. from weekly cron).

> ✅ Validated against a real reference sheet: **all 6 CAR-positive stocks and all 6
> GTT trigger prices for week 2026-W39 were reproduced exactly**
> (KOTAKBANK 420.60 · PNB 118.90 · BAJAJHLDNG 11449.00 · TECHM 1576.20 · GAIL 174.38 · ETERNAL 344.40).

---

## 🚨 Market alert system (instant Telegram alerts)

`alerts` runs after market close and sends **one Telegram message per day:
only the CAR result table** (same columns/order as your reference sheet).
Alert events (table below) are still detected — you see them in the
console/Actions run log, never in Telegram:

| Alert | Fires when | Example |
|---|---|---|
| 🚨 **GTT trigger crossed** | a CAR-positive stock's price reaches last week's high (the GTT level) | `🚨 NSE:ETERNAL crossed its GTT trigger 329.75 — now 335.0 (limit 329.85, qty 15)` |
| 🟢 **CAR flipped positive** | a stock turns `Buy/Average Out` | `🟢 NSE:PNB CAR flipped POSITIVE (streak 41d, CMP 116.6)` |
| 🔴 **CAR flipped negative** | a held/watched stock turns `Avoid Hold` → delete pending GTT | `🔴 NSE:TATASTEEL CAR flipped NEGATIVE → Avoid Hold` |
| ⚡ **Daily move** | price moves ≥ `daily_move_pct` (default 3%) vs previous close | `📈 NSE:AXISBANK +3.0% (1186.50 → 1222.40)` |

**De-duplication:** every event gets a key like `gtt:ETERNAL:2026-W38` or
`move:AXISBANK:2026-09-25`, stored in `logs/alerts_state.json` — re-runs never
detect the same event twice, and `summary:{date}` guarantees at most one
Telegram message per day. The state also remembers the last CAR positive set
so flips can be detected even without a prior report run.

### Run locally

```bash
python -m telegram_repo_alerts alerts              # refresh quotes + check + send
python -m telegram_repo_alerts alerts --dry-run    # preview, nothing written/sent
python -m telegram_repo_alerts alerts --no-refresh # use existing prices file
python -m telegram_repo_alerts alerts --no-send    # update state, print only
python -m telegram_repo_alerts alerts --threshold 2.5   # custom move %
```

### Run automatically via GitHub Actions (recommended) ⏰

The workflow [`.github/workflows/market-alerts.yml`](.github/workflows/market-alerts.yml)
is **only a trigger** — it runs the same Python command; all logic stays in the repo.

1. Push this repository to GitHub (`git remote add origin … && git push -u origin main`).
2. Add the two secrets: **Settings → Secrets and variables → Actions** →
   `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (same as in Quick start).
3. Ensure Actions are enabled for the repo (Actions tab → *enable* if prompted).

That's it. The default schedule is **every day at 17:15 IST (5:15 PM — after
market close): `15 11 * * *` UTC**, so you get one consolidated alert message
each evening with the day's GTT crossings, CAR flips and ±3% moves.
Each run: refresh quotes → detect → Telegram **only if something new** → commit the
updated state file back to the repo (`chore: update alerts de-dup state [skip ci]`).

Notes:
- The state commits also keep the repository "active", so GitHub won't auto-disable
  the scheduled workflow after 60 days of inactivity.
- First run just saves a baseline (the current 6 CAR-positive stocks) — no spam.
- Weekend runs are harmless: data is unchanged, so de-dup reports 0 new alerts.
- Change cadence by editing the `cron` line; e.g. twice daily (1 PM & 5 PM IST):
  `'30 7,11 * * *'`, or during market hours: `'15 4-10 * * 1-5'`.

### 🛟 Troubleshooting — "I am not receiving Telegram alerts"

Work through this checklist in order:

1. **Test your credentials first** (locally, with the env vars set):
   ```bash
   export TELEGRAM_BOT_TOKEN="123456:AAE..."
   export TELEGRAM_CHAT_ID="-100..."
   python -m telegram_repo_alerts test      # ← must arrive as a ping within seconds
   ```
   No ping → fix bot token / chat id (see Quick start step 2). The bot must have
   seen at least one message from you, and for groups/channels it must be an admin.

2. **Try a forced alert run** (bypasses all de-duplication):
   ```bash
   python -m telegram_repo_alerts alerts --no-refresh --force
   ```
   You should receive the full current event list. If this works, the pipe is fine
   and earlier silence was just de-dup/quiet days.

3. **Check the diagnostics line** printed by every run — it states exactly what
   happened: `📨 Telegram: ✅ ... SENT` / `CAR result already sent today` /
   `daily_summary is disabled` / `skipped (--no-send)`.

4. **For automatic 5 PM runs (GitHub Actions):**
   - Is the repo actually **pushed to GitHub** with this code? (`git remote -v` must show a remote)
   - Are the secrets named exactly `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`?
   - Is the **Actions** tab enabled, and is `market-alerts.yml` on the **default branch**?
   - Open the latest workflow run (must be ✅) and read the *Check alerts* step log —
     the same diagnostics print there. A failed step = error shown in the log.

5. **Failed sends never burn alerts** (bug fixed): if credentials are missing or
   Telegram errors, nothing is marked as sent — the run exits with a clear `❌`
   and retries next time. State is only saved **after** a successful send.

6. **Quiet-day silence is gone**: with `alerts.daily_summary: true` (default) the
   scheduled run sends the **daily CAR result table** (same columns as the sheet:
   `NSE Code | CMP | Difference from 200 DMA | CAR Rating | Trigger Price for GTT`,
   sorted by difference ascending) **every day after 5 PM**, even with 0 events.
   The table is the ONLY thing Telegram receives (≤1 message/day) — alert events
   appear in the run log instead. Disable with `--no-summary` for silence.

## 🕘 Making it run automatically — 3 options

### Option A — The built-in Python scheduler (simplest) ✅

```bash
python -m telegram_repo_alerts schedule
```

Set it and forget it — the process sleeps until the next `schedule.time` and fires itself.
Works on any always-on machine (laptop, VPS, Raspberry Pi, old phone server…).

### Option B — systemd (Linux server, auto-restart on reboot)

`/etc/systemd/system/telegram-repo-alerts.service`:

```ini
[Unit]
Description=Telegram repo alerts (pure Python)
After=network-online.target

[Service]
WorkingDirectory=/opt/telegram-repo-alerts
Environment=TELEGRAM_BOT_TOKEN=123456:AAE...
Environment=TELEGRAM_CHAT_ID=-1001234567890
ExecStart=/usr/bin/python3 -m telegram_repo_alerts schedule
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-repo-alerts
```

### Option C — plain cron (run once per day)

```cron
# every day 09:00 local time
0 9 * * * cd /opt/telegram-repo-alerts && TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... /usr/bin/python3 -m telegram_repo_alerts run-once >> alerts.log 2>&1
```

### 🐳 Docker (optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
CMD ["python", "-m", "telegram_repo_alerts", "schedule"]
```

```bash
docker build -t repo-alerts .
docker run -d --name repo-alerts --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_CHAT_ID=... repo-alerts
```

---

## ⚙️ Configuration reference (`config.json`)

| Key | Meaning | Default |
|---|---|---|
| `monitor_repo` | Repository to watch (`owner/name`) — or use `--repo` / `MONITOR_REPO` env | *(required)* |
| `lookback_hours` | How far back each digest looks | `24` |
| `max_events` | Cap on events per digest | `120` |
| `schedule.mode` | `daily` (at `HH:MM`) or `interval` (every `every_hours`) | `daily` |
| `schedule.time` | Daily fire time, 24h | `09:00` |
| `schedule.timezone` | [IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) | `Asia/Kolkata` |
| `schedule.every_hours` | Used by `interval` mode | `24` |
| `data.source` | Which lists `download` uses by default: `nifty` \| `custom` \| `both` | `both` |
| `data.nifty_csv` | 📝 Path to the **replace-every-6-months** index constituents CSV | `data/nifty_100.csv` |
| `data.watchlist_csv` | 📝 Path to your **custom stock list** CSV | `data/stock_list.csv` |
| `data.output_dir` | Where downloaded prices are written | `data/prices` |
| `data.period` / `data.interval` | yfinance window (`6mo`,`1y`,`2y`,`5y`,`max`) & bar size (`1d`,`1wk`) | `2y` / `1d` |
| `data.suffix` | Exchange suffix appended to symbols (NSE = `.NS`) | `.NS` |
| `report.log` | Append-only CAR results log (stored in the repo) | `logs/car_log.csv` |
| `report.car_days` | Consecutive rising days needed for *Buy/Average Out* | `10` |
| `report.send_telegram` | Auto-send the report as a Telegram message on every `report` run | `false` |
| `alerts.enabled` | Master switch for the alert engine | `true` |
| `alerts.send_telegram` | Send detected alerts to Telegram (off = print/log only) | `true` |
| `alerts.daily_summary` | Send the daily CAR result table as the day's only Telegram message | `true` |
| `alerts.gtt_trigger` | Alert when a CAR-positive stock crosses last week's high | `true` |
| `alerts.car_flip` | Alert when CAR flips positive 🟢 / negative 🔴 | `true` |
| `alerts.daily_move_pct` | Alert on daily move ≥ this % (0 disables) | `3.0` |
| `alerts.car_days` | CAR streak rule used by the alert engine | `10` |
| `alerts.state_file` | De-dup state (kept in repo, committed by Actions) | `logs/alerts_state.json` |
| `enabled_events` | `push`, `issues`, `pull_request`, `star`, `fork`, `release`, `create`, `delete`, `comment`, `review`, `member`, `public` | all |
| `message.header` / `.footer` / `.empty_note` | Digest text (HTML allowed) | see file |
| `message.show_empty_note` | Send "✅ no activity" on quiet days? | `true` |

**Environment variables:** `TELEGRAM_BOT_TOKEN` *(required)* · `TELEGRAM_CHAT_ID` *(required)* ·
`TELEGRAM_MESSAGE_THREAD_ID` *(optional forum topic)* · `GITHUB_TOKEN` *(optional)* ·
`MONITOR_REPO` · `DIGEST_FILE` · `CONFIG_FILE` · `DRY_RUN=1`

---

## 🧪 Testing

```bash
# preview the Telegram payload without sending
python -m telegram_repo_alerts run-once --dry-run

# build digest only, then inspect it
python -m telegram_repo_alerts fetch && cat digest.txt

# offline test with a saved events JSON (no GitHub API calls)
EVENTS_FILE=sample_events.json python -m telegram_repo_alerts fetch --repo me/demo

# unit-style checks without pytest
python - <<'EOF'
from datetime import datetime, timezone
from telegram_repo_alerts.scheduler import next_fire_time
from telegram_repo_alerts.sender import pack_lines

t = next_fire_time(datetime.now(timezone.utc), mode="daily", at="09:00", tz="Asia/Kolkata")
print("next daily fire:", t.isoformat())
print("chunking ok:", all(len(c) <= 4096 for c in pack_lines(["x" * 100] * 500)))
EOF
```

## 📨 Example Telegram message

```
📦 GitHub Repo Digest
📁 yourname/your-repo · 🕐 last 24h · 5 event(s) · ⭐ 132
  🔀 3 push · 🆕 1 issues · ⭐ 1 star

🔀 Push · main · 2 commit(s) · by alice
   • a1b2c3d fix: handle empty digest file
   • e4f5a6b docs: add setup screenshots
🆕 Issue #42 opened by bob
   Build fails on Python 3.12
⭐ Starred by carol
```

## 🔐 Security notes

- Credentials live in **environment variables only** — never in code (`.env` is git-ignored).
- The GitHub token is optional and only used to read public repo metadata.
- Telegram delivery validates HTML, retries with backoff (429/5xx) and degrades
  gracefully to plain text if parsing fails.

## 📄 License

MIT — see [LICENSE](LICENSE).
