# scanner.py
# Binance Spot USDT EMA20/50 bullish crossover screener (4H) + Telegram alerts
#
# ✅ Scans ALL Binance SPOT USDT symbols (TRADING)
# ✅ Detects EMA20 crossing ABOVE EMA50 on 4H
# ✅ Classifies signal age within last 48h (12 x 4H candles):
#    - 0 (fresh), 1, 2, 4, 5 candles ago (only these are reported)
# ✅ Shows ONLY:
#    - Coin name
#    - Age bucket (0/1/2/4/5 candles ago)
#    - EMA100 & EMA200 on 4H
#    - EMA100 & EMA200 on 1D
# ✅ Telegram alert with TradingView chart link
# ✅ GitHub Actions friendly (uses TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from ENV)
#
# Requirements:
#   pip install aiohttp pandas

import os
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

BINANCE_REST = "https://api.binance.us"
IST = timezone(timedelta(hours=5, minutes=30))

# Telegram ENV (set via GitHub Secrets -> Actions)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Tuning
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "25"))
PER_SYMBOL_DELAY_SEC = float(os.getenv("PER_SYMBOL_DELAY_SEC", "0.03"))
TG_BETWEEN_MSG_DELAY_SEC = float(os.getenv("TG_BETWEEN_MSG_DELAY_SEC", "0.7"))

# Candles
INTERVAL_4H = "4h"
INTERVAL_1D = "1d"
LIMIT_4H = int(os.getenv("LIMIT_4H", "260"))   # enough for EMA200 + buffer
LIMIT_1D = int(os.getenv("LIMIT_1D", "260"))

# Only these "age buckets" requested
ALLOWED_AGES = {0, 1, 2, 4, 5}


def tv_chart_link(symbol: str) -> str:
    # Best practical universal link; often opens the TradingView app if supported links enabled
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def to_float_list(klines: List[List]) -> Tuple[List[float], List[int]]:
    closes = [float(k[4]) for k in klines]
    close_times_ms = [int(k[6]) for k in klines]  # closeTime
    return closes, close_times_ms


async def http_get_json(session: aiohttp.ClientSession, url: str, params: Dict) -> Dict:
    async with session.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url} params={params} body={txt[:200]}")
        return await resp.json()


async def get_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int) -> List[List]:
    url = f"{BINANCE_REST}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    async with session.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"KLINES HTTP {resp.status} {symbol} {interval}: {txt[:200]}")
        return await resp.json()


async def get_usdt_spot_symbols(session: aiohttp.ClientSession) -> List[str]:
    url = f"{BINANCE_REST}/api/v3/exchangeInfo"
    data = await http_get_json(session, url, params={})
    symbols = []
    for s in data.get("symbols", []):
        # Spot trading symbols, USDT quote, TRADING status
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        sym = s.get("symbol", "")
        # Commonly exclude leveraged tokens etc. (optional)
        # If you want literally everything, comment this block out:
        bad_suffix = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
        if sym.endswith(bad_suffix):
            continue
        symbols.append(sym)
    return symbols


def find_bullish_cross_ages(closes: List[float]) -> List[int]:
    """
    Returns list of ages (candles ago) where a bullish cross happened:
    bullish cross at index i means EMA20[i] > EMA50[i] and EMA20[i-1] <= EMA50[i-1]
    age = (last_index - i)
    """
    if len(closes) < 60:
        return []

    s = pd.Series(closes, dtype="float64")
    e20 = ema(s, 20)
    e50 = ema(s, 50)

    crosses = []
    last = len(s) - 1

    # Scan last 12 candles window only (48 hours on 4H)
    # But EMAs computed on entire series.
    start = max(1, len(s) - 12)
    for i in range(start, len(s)):
        if (e20.iloc[i] > e50.iloc[i]) and (e20.iloc[i - 1] <= e50.iloc[i - 1]):
            crosses.append(last - i)

    return crosses


def compute_ema_values(closes: List[float]) -> Dict[str, float]:
    s = pd.Series(closes, dtype="float64")
    e100 = float(ema(s, 100).iloc[-1])
    e200 = float(ema(s, 200).iloc[-1])
    return {"ema100": e100, "ema200": e200}


async def scan_symbol(session: aiohttp.ClientSession, sem: asyncio.Semaphore, symbol: str) -> Optional[Dict]:
    await asyncio.sleep(PER_SYMBOL_DELAY_SEC)

    async with sem:
        try:
            kl4h = await get_klines(session, symbol, INTERVAL_4H, LIMIT_4H)
            if not isinstance(kl4h, list) or len(kl4h) < 210:
                return None

            closes_4h, close_times_4h = to_float_list(kl4h)
            ages = find_bullish_cross_ages(closes_4h)
            # keep only requested ages
            ages = [a for a in ages if a in ALLOWED_AGES]
            if not ages:
                return None

            # 4H EMA100/200 (only show these)
            ema4h = compute_ema_values(closes_4h)

            # 1D EMA100/200
            kld = await get_klines(session, symbol, INTERVAL_1D, LIMIT_1D)
            if not isinstance(kld, list) or len(kld) < 210:
                return None
            closes_1d, _ = to_float_list(kld)
            ema1d = compute_ema_values(closes_1d)

            # Use last closed 4H candle close time as "run context"
            last_close_ms = close_times_4h[-1]
            last_close_ist = datetime.fromtimestamp(last_close_ms / 1000, tz=timezone.utc).astimezone(IST)

            return {
                "symbol": symbol,
                "ages": sorted(set(ages)),
                "ema4h_100": ema4h["ema100"],
                "ema4h_200": ema4h["ema200"],
                "ema1d_100": ema1d["ema100"],
                "ema1d_200": ema1d["ema200"],
                "last4h_close_ist": last_close_ist.strftime("%Y-%m-%d %H:%M IST"),
                "tv": tv_chart_link(symbol),
            }
        except Exception as e:
            # Keep scanning others; print minimal error for diagnostics
            print(f"[WARN] {symbol} scan failed: {e}")
            return None


def group_by_age(results: List[Dict]) -> Dict[int, List[Dict]]:
    buckets = {0: [], 1: [], 2: [], 4: [], 5: []}
    for r in results:
        for age in r["ages"]:
            if age in buckets:
                buckets[age].append(r)
    # Sort each bucket by symbol
    for k in buckets:
        buckets[k] = sorted(buckets[k], key=lambda x: x["symbol"])
    return buckets


def fmt_num(x: float) -> str:
    # Compact formatting for Telegram
    # Use more decimals for very small prices
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def build_message(results: List[Dict]) -> str:
    now_ist = datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
    total = len(results)

    header = [
        "EMA Screener (Binance Spot USDT)",
        f"Run: {now_ist}",
        f"Signals: {total}",
        "",
        "Rule: EMA20 crossed ABOVE EMA50 on 4H (ages: 0/1/2/4/5 candles ago)",
        "",
    ]

    if total == 0:
        header.append("No signals in the last 48 hours (4H).")
        return "\n".join(header)

    buckets = group_by_age(results)

    lines = header
    for age in [0, 1, 2, 4, 5]:
        items = buckets[age]
        if not items:
            continue

        title = "FRESH (0 candle ago)" if age == 0 else f"{age} candle(s) ago"
        lines.append(f"== {title} ==")

        # 48 hrs data requirement: "only name" (here: we list names under each bucket)
        # Then for each coin we show only EMA100/200 values (4H & 1D) + TV link.
        for r in items:
            sym = r["symbol"]
            lines.append(f"{sym}")
            lines.append(
                f"4H EMA100: {fmt_num(r['ema4h_100'])} | 4H EMA200: {fmt_num(r['ema4h_200'])}"
            )
            lines.append(
                f"1D EMA100: {fmt_num(r['ema1d_100'])} | 1D EMA200: {fmt_num(r['ema1d_200'])}"
            )
            lines.append(f"TV: {r['tv']}")
            lines.append("")  # spacer

    return "\n".join(lines).strip()


async def telegram_send_with_retry(session: aiohttp.ClientSession, text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[INFO] Telegram not configured (missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID). Printing message:\n")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    # Retry for flood control / transient errors
    for attempt in range(1, 8):
        try:
            async with session.post(url, data=payload, timeout=REQUEST_TIMEOUT_SEC) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and data.get("ok") is True:
                    return True

                # Handle rate limiting
                if resp.status == 429:
                    retry_after = None
                    try:
                        retry_after = int(data.get("parameters", {}).get("retry_after", 2))
                    except Exception:
                        retry_after = 2
                    wait = max(2, retry_after) + 1
                    print(f"[WARN] Telegram 429 rate limit. Waiting {wait}s then retry (attempt {attempt})")
                    await asyncio.sleep(wait)
                    continue

                # Other errors
                print(f"[WARN] Telegram send failed (HTTP {resp.status}): {str(data)[:250]}")
                await asyncio.sleep(min(2 ** attempt, 20))
        except Exception as e:
            print(f"[WARN] Telegram exception: {e} (attempt {attempt})")
            await asyncio.sleep(min(2 ** attempt, 20))

    return False


async def telegram_send_chunked(session: aiohttp.ClientSession, text: str) -> None:
    """
    Telegram message length limit ~4096 chars.
    Unlimited results => chunk message.
    """
    if not text:
        return

    MAX_LEN = 3800
    parts = []
    buf = ""
    for line in text.splitlines():
        add = (line + "\n")
        if len(buf) + len(add) > MAX_LEN:
            parts.append(buf.rstrip())
            buf = ""
        buf += add
    if buf.strip():
        parts.append(buf.rstrip())

    # Send parts sequentially (prevents flood)
    for i, part in enumerate(parts, start=1):
        await telegram_send_with_retry(session, part)
        if i != len(parts):
            await asyncio.sleep(TG_BETWEEN_MSG_DELAY_SEC)


async def main():
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENCY * 2, ssl=False)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession(connector=connector) as session:
        symbols = await get_usdt_spot_symbols(session)
        print(f"Symbols found: {len(symbols)}")

        tasks = [scan_symbol(session, sem, s) for s in symbols]
        scanned = await asyncio.gather(*tasks)

        results = [r for r in scanned if r is not None]
        print(f"Signals found: {len(results)}")

        msg = build_message(results)
        await telegram_send_chunked(session, msg)


if __name__ == "__main__":
    asyncio.run(main())
