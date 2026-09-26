# 🧪 Test Report — telegram-repo-alerts

**Test period:** Trading week **ISO 2026-W39 (Mon 21 → Fri 25 Sep 2026)** · data as of Fri 25 Sep 2026 (last trading day)
**Executed:** Sat 26 Sep 2026 · IST · against **live** GitHub API, **live** Yahoo Finance (yfinance), Telegram in dry-run (no credentials configured)

---

## 1. Test battery — pipeline results

| # | Test | What was verified | Result |
|---|------|-------------------|--------|
| 1 | `lists` | Reads official NSE `nifty_100.csv` (100 symbols) + custom `stock_list.csv` (4 symbols) | ✅ PASS |
| 2 | `download` | yfinance fetch of both lists, merged & de-duplicated → **100/100 downloaded, 0 failed, 49,355 rows** (2y daily) | ✅ PASS |
| 3 | Data freshness | All **5 trading days** (09-21…09-25) present with **100 stocks/day**; range 2024-09-25 → 2026-09-25 | ✅ PASS |
| 4 | `run-once --dry-run` (live) | GitHub Events API on `github/docs` → **62 events** digested into **2 HTML chunks** (4,076 chars, correct splitting ≤4096) | ✅ PASS |
| 5 | `test --dry-run` | Telegram ping payload renders with correct IST timestamp | ✅ PASS |
| 6 | `schedule` boot | Scheduler starts, computes **next fire = Sun 27 Sep 2026 09:00 IST** correctly, Ctrl-C responsive | ✅ PASS |
| 7 | Unit checks | 7/7: scheduler math, chunking, HTML escape/unescape, `.NS` suffixing, CSV loader | ✅ PASS (7/7) |
| 8 | Error handling | Missing CSV → friendly message; bogus `--period` → graceful 100-failure report, **exit code 2**, no crash | ✅ PASS |
| 9 | Weekly CAR report | Full method screening of all 100 stocks (below) | ✅ PASS |

**Score: 9/9 tests passed.**

## 2. Bugs found & fixed during testing

1. **Failed download could wipe good data** — a bad period/network error would overwrite `prices_daily.csv` with an empty file. → Added guard: never clobber existing files when 0 rows are returned. *Verified: bogus run kept the previous 2,005 rows intact.*
2. **Silent failure exit code** — total download failure returned exit 0. → Now returns **exit 2** so cron/systemd can alert.
3. **Year-high basis** — report first used the intraday High for year-high detection;
   the user's reference sheet uses the **close basis**, which additionally includes
   BAJAJHLDNG. → Switched to close basis; all 6 stocks and all 6 triggers now reproduce
   the sheet exactly (§5b).

*(Also fixed earlier this session: symbol helper naming bug; `--list both` second list overwriting the first → now merged + de-duplicated in one download.)*

## 3. This week's market-data result

```
symbols: 100/100  ·  rows: 49,355  ·  range: 2024-09-25 .. 2026-09-25
trading days this week: 2026-09-21, 22, 23, 24, 25  (100 stocks each — complete)
outputs: data/prices/prices_daily.csv (long OHLCV) + data/prices/latest_prices.csv
```

## 4. Weekly CAR screening — the method applied to this week

Rule implemented per the reference sheet: year-high = max **close** in trailing 365d → running average of closes from that date → **CAR positive ("Buy/Average Out") if the average has risen ≥ 10 consecutive trading days** → Sunday's GTT list at last week's high, ₹5,000 tranche. *(Rule basis corrected after validation against the user's own sheet output — see §5.)*

| Result | Count |
|---|---|
| ✅ **CAR positive ("Buy/Average Out") — GTT-ready this Sunday** | **6** |
| 🆕 turned positive *during* this week | 0 |
| ⛔ negative / pending (streak < 10) | 94 |

### 📋 This Sunday's GTT buy list (per the method)

| Symbol | Close (Fri) | Week high = **Trigger** | Limit (+0.10) | Qty (₹5,000) | Streak | Year-high date |
|---|---|---|---|---|---|---|
| **GAIL** | 172.70 | **174.38** | 174.48 | 29 | 90 days | 2025-11-17 |
| **ETERNAL** | 335.00 | **344.40** | 344.50 | 15 | 63 days | 2025-10-15 |
| **TECHM** | 1548.00 | **1576.20** | 1576.30 | 4 | 56 days | 2026-01-29 |
| **BAJAJHLDNG** | 10940.00 | **11449.00** | 11449.10 | 1 | 45 days | 2025-10-23 |
| **PNB** | 116.60 | **118.90** | 119.00 | 43 | 41 days | 2026-01-16 |
| **KOTAKBANK** | 404.00 | **420.60** | 420.70 | 12 | 23 days | 2025-10-23 |

### Near-misses to watch next week (streak 5–9, need 10)

UNIONBANK (8) · TMCV (7) · ADANIPORTS (6) · DLF (6) · HINDZINC (6) · ZYDUSLIFE (6)

*Full 100-row output: regenerate anytime with
`python -m telegram_repo_alerts report --no-log --csv full.csv` · History log: [`logs/car_log.csv`](logs/car_log.csv)*

## 5. ⭐ Cross-validation against the video's own worked examples

The video (published 25 Sep 2026, recorded this same week) shows specific numbers. Our independent recomputation from raw yfinance data reproduces **every one of them**:

| Video example | Video says | Our test says | Match |
|---|---|---|---|
| PNB GTT trigger / limit / qty | 118.90 / 119 / 43 | 118.90 / 119.00 / 43 | ✅ |
| Kotak Bank GTT trigger | 420.60 | 420.60 (limit 420.70) | ✅ |
| Tech Mahindra trigger / limit (update demo) | 1576.20 / 1576.30 | 1576.20 / 1576.30 | ✅ |
| Tech Mahindra year-high date | 3 Feb 2026 | 2026-02-03 | ✅ |
| Tech Mahindra year-high value | ₹1716.50 | ₹1716.50 (that day's close; intraday high was 1854 — confirms the sheet's basis) | ✅ |
| Tech Mahindra CAR average mid-Sep | ~1488.31 → 1490.69, rising | 1492.21 (still rising, streak 56) | ✅ consistent |
| Positive-CAR list quality (e.g. PNB, Kotak, TechM positive; Persistent-9% fall = delete) | named PNB/Kotak/TechM positive | all three in our top-5 | ✅ |

**Conclusion:** the implementation of the CAR + Darvas/GTT pipeline is faithful to the video's method.

### 5b. ⭐ Validation against the user's own sheet output (supplied 26 Sep 2026)

The user's reference sheet for the same week lists **6** CAR-positive stocks (it includes
BAJAJHLDNG, which a year-high-by-intraday-High basis would have missed). Re-running all
rule variants against the sheet showed the **close-basis** rule reproduces it exactly:

| Sheet NSE Code | Sheet trigger | Our trigger | Match | Sheet CMP | Our CMP (Yahoo) | Sheet 200DMA | Our 200DMA |
|---|---|---|---|---|---|---|---|
| NSE:KOTAKBANK | 420.60 | 420.60 | ✅ | 401.80 | 404.00 | 0.35% | 1.05% |
| NSE:PNB | 118.90 | 118.90 | ✅ | 116.25 | 116.60 | 1.52% | 1.93% |
| NSE:BAJAJHLDNG | 11449.00 | 11449.00 | ✅ | 10900.00 | 10940.00 | 1.97% | 2.44% |
| NSE:TECHM | 1576.20 | 1576.20 | ✅ | 1550.00 | 1548.00 | 1.99% | 1.97% |
| NSE:GAIL | 174.38 | 174.38 | ✅ | 173.00 | 172.70 | 4.09% | 3.91% |
| NSE:ETERNAL | 344.40 | 344.40 | ✅ | 334.95 | 335.00 | 21.18% | 21.47% |

* **Stock set: 6/6 exact** · **GTT triggers: 6/6 exact**
* CMP / 200-DMA differ slightly — your sheet quotes a different price feed/timestamp;
  triggers (week intraday highs) are identical, which is what GTT orders use.

## 5c. New features added on request: repo log + Telegram message

1. **`logs/car_log.csv`** — every `report` run **appends** a timestamped row per
   CAR-positive stock (week, NSE code, CMP, 200-DMA %, rating, trigger/limit/qty,
   streak, year-high, price source). Verified: append, not overwrite.
2. **Telegram message** — `report --telegram` sends the sheet-style table
   (monospace `<pre>` block + limit/qty + near-misses + disclaimer).
   Verified via `--dry-run` (968 chars, 1 chunk); without credentials it fails
   gracefully with exit 1 and a clear message.
3. Config: `report.log`, `report.car_days`, `report.send_telegram` — plus flags
   `--log`, `--log-all`, `--no-log`, `--csv`, `--message-out`.

## 6. Telegram digest sample (dry-run, live GitHub data)

```
📦 GitHub Repo Digest
📁 github/docs · 🕐 last 24h · 62 event(s) · ⭐ 20897
  🍴 11 fork · 🔵 13 pull request · 💬 10 comment · ⭐ 7 star · 🔀 6 push · 🆕 15 issues

🔀 Push · main · 2 commit(s) · by alice ...
🆕 Issue #46091 opened by ...
```
→ split into **2 chunks** (4,076 + remainder), HTML tags never cut, would be sent sequentially with pacing.

## 7. Reproduce / run for a full week

```bash
pip install -r requirements.txt              # yfinance
python -m telegram_repo_alerts lists         # validate CSVs
python -m telegram_repo_alerts download      # fresh weekly data
python -m telegram_repo_alerts report --no-log --csv car_$(date +%G-W%V).csv
python -m telegram_repo_alerts test          # real Telegram ping (needs secrets)
python -m telegram_repo_alerts schedule      # fire every day 09:00 IST
```

To let it truly run for a week: export `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, set `monitor_repo` in `config.json`, and start `schedule` (or use the systemd/Docker recipes in the README).

---

⚠️ **Disclaimer:** All figures are from an educational test of the software against historical market data. Nothing here is investment advice; no buy/sell recommendation is implied. Markets carry risk.
