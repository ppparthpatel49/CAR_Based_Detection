"""
market_data.py — Download NSE price data with yfinance.

Two swappable CSV lists (both customizable by you):

  * data/nifty_100.csv    -> the official Nifty 100 index constituents.
                             Replace it every ~6 months when NSE rebalances
                             (download from the Nifty/niftyindices site:
                              "Nifty 100 constituents" CSV). The official NSE
                              columns (Company Name, Industry, Symbol, Series,
                              ISIN Code) all work — only the Symbol column is
                              required.

  * data/stock_list.csv   -> your own free-form watchlist (Symbol + optional
                             Name/Notes). Upload/edit any time.

Downloaded history is written as one long-format CSV plus a latest-close
snapshot, ready for analysis (e.g. the CAR method from the concept video).

NOTE: yfinance is a third-party package (`pip install yfinance`); everything
else in this repository still uses only the standard library.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path

from . import config as cfg

ROOT = Path(__file__).resolve().parent.parent

# Columns accepted as "the symbol column" (first match wins)
SYMBOL_COLUMNS = ("symbol", "ticker", "scrip", "stock", "code")
# Rows whose symbol looks like a header leftover are skipped
HEADER_TOKENS = {"symbol", "ticker", "scrip", "stock", "code", "nse symbol"}


# --------------------------------------------------------------------------- CSV
def _clean_symbol(raw: str) -> str:
    sym = (raw or "").strip().strip('"').strip().upper()
    if "." in sym:  # tolerate yfinance style RELIANCE.NS
        sym = sym.split(".", 1)[0]
    return sym


def load_symbols(path: str | os.PathLike) -> list[str]:
    """
    Read symbols from any reasonable CSV layout:
      * official NSE index files  (Company Name, Industry, Symbol, ...)
      * simple one-column lists   (one symbol per line, optional header)
      * custom watchlists         (Symbol, Name, Notes, ...)

    Returns a de-duplicated list in file order. Raises a friendly error when
    the file is missing or contains no usable symbols.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"❌ Stock list not found: {path}\n"
            f"   Create it or update data_paths in config.json.")

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    # locate the symbol column in the first ~10 non-empty rows
    sym_idx = 0
    for row in rows[:10]:
        for i, cell in enumerate(row):
            if cell.strip().strip('"').lower() in SYMBOL_COLUMNS:
                sym_idx = i
                break
        else:
            continue
        break

    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        if not row or sym_idx >= len(row):
            continue
        sym = _clean_symbol(row[sym_idx])
        if not sym or sym.lower() in HEADER_TOKENS:
            continue
        # basic sanity: NSE symbols are A-Z, 0-9, & - . _
        if not all(c.isalnum() or c in "&-_. " for c in sym):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        out.append(sym)

    if not out:
        raise ValueError(f"❌ No usable symbols found in {path}")
    return out


def resolve_lists(config: dict, which: str) -> list[tuple[str, list[str]]]:
    """Return [(list_name, symbols), ...] for which in nifty|custom|both."""
    data_cfg = config.get("data", {})
    sources: list[tuple[str, str]] = []
    if which in ("nifty", "both"):
        sources.append(("nifty_100", data_cfg.get("nifty_csv", "data/nifty_100.csv")))
    if which in ("custom", "both"):
        sources.append(("stock_list", data_cfg.get("watchlist_csv", "data/stock_list.csv")))

    resolved = []
    for name, path in sources:
        abs_path = Path(path)
        if not abs_path.is_absolute():
            abs_path = ROOT / path
        try:
            resolved.append((name, load_symbols(abs_path)))
        except FileNotFoundError as exc:
            if which == "both":  # tolerate a missing optional custom list
                print(f"⚠️  {exc}")
                continue
            raise
    return resolved


# ---------------------------------------------------------------------- download
def _yf():
    try:
        import yfinance  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "❌ yfinance is not installed. Install it with:\n"
            "   pip install yfinance   (or: pip install -r requirements.txt)"
        ) from exc
    return yfinance


def to_yahoo_symbol(symbol: str, suffix: str = ".NS") -> str:
    return symbol if symbol.endswith(suffix) else f"{symbol}{suffix}"


def download_history(symbols: list[str], *, period: str = "2y", interval: str = "1d",
                     suffix: str = ".NS", output_dir: str | os.PathLike = "data/prices") -> dict:
    """
    Download daily OHLCV history for `symbols` via yfinance.

    Writes:
      <output_dir>/prices_daily.csv   long format: symbol,date,open,high,low,close,volume
      <output_dir>/latest_prices.csv  snapshot:  symbol,date,close

    Returns a summary dict {downloaded, failed:[...], rows, files:[...]}.
    """
    yf = _yf()
    out_dir = Path(output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    yahoo_symbols = [to_yahoo_symbol(s, suffix) for s in symbols]
    print(f"⬇️  Downloading {len(yahoo_symbols)} symbol(s) "
          f"[period={period}, interval={interval}] via yfinance …", flush=True)

    raw = yf.download(
        tickers=yahoo_symbols,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )

    # --- reshape MultiIndex (ticker, field) -> long format --------------
    import pandas as pd  # hard dependency of yfinance

    long_rows: list[list] = []
    latest_rows: list[list] = []
    failed: list[str] = []

    def frame_for(ticker: str):
        if raw is None or len(raw) == 0:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker not in raw.columns.get_level_values(0):
                return None
            df = raw[ticker]
        else:
            df = raw
        df = df.dropna(how="all")
        return df if len(df) else None

    for sym, yahoo in zip(symbols, yahoo_symbols):
        df = frame_for(yahoo)
        if df is None:
            failed.append(sym)
            continue
        for dt, row in df.iterrows():
            date_s = getattr(dt, "date", lambda: dt)().isoformat() \
                if hasattr(dt, "date") else str(dt)[:10]
            close = row.get("Close")
            if close is None or str(close) == "nan":
                continue
            long_rows.append([
                sym, date_s,
                _num(row.get("Open")), _num(row.get("High")),
                _num(row.get("Low")), _num(close),
                _num(row.get("Volume"), ints=True),
            ])
        last = df.dropna(subset=["Close"])
        if len(last):
            dt = last.index[-1]
            date_s = getattr(dt, "date", lambda: dt)().isoformat() \
                if hasattr(dt, "date") else str(dt)[:10]
            latest_rows.append([sym, date_s, _num(last["Close"].iloc[-1])])

    prices_file = out_dir / "prices_daily.csv"
    latest_file = out_dir / "latest_prices.csv"

    # never clobber existing data with an empty file (e.g. bad period,
    # network outage, wrong suffix) — keep the last good download instead
    if not long_rows:
        print("⚠️  No rows returned — keeping previously downloaded files untouched.",
              flush=True)
        existing = [str(p) for p in (prices_file, latest_file) if p.exists()]
        return {"downloaded": 0, "failed": failed, "rows": 0,
                "files": existing, "as_of": datetime.now().strftime("%Y-%m-%d %H:%M")}

    with open(prices_file, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        w.writerows(long_rows)

    with open(latest_file, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "date", "close"])
        w.writerows(sorted(latest_rows))

    return {
        "downloaded": len(latest_rows),
        "failed": failed,
        "rows": len(long_rows),
        "files": [str(prices_file), str(latest_file)],
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _num(value, ints: bool = False):
    try:
        import math
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        return int(value) if ints else round(float(value), 4)
    except Exception:
        return ""


# --------------------------------------------------------------------- summary
def list_summary(config: dict) -> list[dict]:
    """Validate both CSV lists and return [{name, path, count, sample}, ...]"""
    out = []
    for name, path in (("nifty_100", config.get("data", {}).get("nifty_csv", "data/nifty_100.csv")),
                       ("stock_list", config.get("data", {}).get("watchlist_csv", "data/stock_list.csv"))):
        abs_path = Path(path)
        if not abs_path.is_absolute():
            abs_path = ROOT / path
        entry = {"name": name, "path": str(abs_path)}
        try:
            syms = load_symbols(abs_path)
            entry.update(count=len(syms), sample=", ".join(syms[:5]))
        except (FileNotFoundError, ValueError) as exc:
            entry.update(count=0, sample=str(exc).splitlines()[0])
        out.append(entry)
    return out
