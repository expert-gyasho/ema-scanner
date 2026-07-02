# scanner.py
# Binance Spot USDT EMA20/50 bullish crossover screener (4H)
# - Scans all Binance SPOT USDT symbols (TRADING)
# - Detects last bullish EMA20 cross above EMA50 within last 48h (12 x 4H candles)
# - Alerts only if crossover was 0 / 1 / 2 / 4 / 5 candles ago
# - Shows ONLY: coin name + (how many candles ago) + EMA100/200 on 4H + EMA100/200 on 1D
# - Telegram alert + TradingView chart link (best universal https chart link)
# - Designed for GitHub Actions scheduled runs on IST candle closes

import os
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

BINANCE_REST = "https://api.binance.com"
IST = timezone(timedelta(hours=5, minutes=30))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
PER_SYMBOL_DELAY_SEC = float(os.getenv("PER_SYMBOL_DELAY_SEC", "0.03"))

# How many candles to fetch for EMA stability
CANDLE_LIMIT_4H = int(os.getenv("CANDLE_LIMIT_4H", "220"))
CANDLE_LIMIT_1D = int(os.getenv("CANDLE_LIMIT_1D", "260"))

# Only these offsets (candles ago) should be reported
OFFSETS_ALLOWED = {0, 1, 2, 4, 5}

# Telegram message max length (Telegram hard limit is 4096)
TG_CHUNK_SIZE = 3500

# Small delay between Telegram messages to reduce flood risk
TG_BETWEEN_MSG_DELAY_SEC = float(os.getenv("TG_BETWEEN_MSG_DELAY_SEC", "0.7"))


def tv_chart_link(symbol: str) -> str:
    # Best universal chart link; opens in app on many phones if supported links are enabled
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"


def tv_symbol_page(symbol: str) -> str:
    # Fallback page
    return f"https://www.tradingview.com/symbols/{symbol}/?exchange=BINANCE"


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def find_last_bullish_cross_offset(
    close: pd.Series,
    max_lookback: int = 12
) -> Optional[int]:
    """
    Returns offset (0 = latest closed candle) for the most recent bullish cross
    within max_lookback candles, else None.

    Bullish cross definition:
      EMA20 crosses from <= EMA50 to > EMA50 at candle i
    """
    e20 = ema(close, 20)
    e50 = ema(close, 50)

    # We check crosses on closed candles. close.iloc[-1] is latest candle close returned by Binance.
    # We'll look back max_lookback candles from the end.
    n = len(close)
    if n < 60:
        return None

    # Convert to lists for speed
    e20v = e20.values
    e50v = e50.values

    # i is index in series; we detect cross at i comparing i-1 and i
    # Search from most recent backwards, within lookback window.
    start_i = max(1, n - max_lookback)  # ensure i-1 exists
    for i in range(n - 1, start_i - 1, -1):
        prev = i - 1
        if e20v[prev] <= e50v[prev] and e20v[i] > e50v[i]:
            offset = (n - 1) - i
            return offset
    return None


async def fetch_json(session: aiohttp.ClientSession, url: str, params: Dict) -> Optional[dict]:
    """
    Fetch JSON with timeout. Handles Binance HTTP 451 (restricted location) gracefully by
    returning an empty dict so callers can decide how to proceed instead of crashing the job.
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with session.get(url, params=params, timeout=timeout) as resp:
        # Binance sometimes returns JSON on error too
        # Use content_type=None to allow non-standard content-types
        try:
            data = await resp.json(content_type=None)
        except Exception:
            # fallback to text if JSON parsing fails
            text = await resp.text()
            data = {"_raw": text}

        if resp.status == 451:
            print(f"[WARN] HTTP 451 from {url}: {str(data)[:300]}")
            return {}
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}: {str(data)[:300]}")
        return data


async def get_usdt_spot_symbols(session: aiohttp.ClientSession) -> List[str]:
    url = f"{BINANCE_REST}/api/v3/exchangeInfo"
    data = await fetch_json(session, url, params={})

    if not data:
        print("[WARN] exchangeInfo unavailable or empty; returning no symbols")
        return []

    symbols = []
    for s in data.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        # Spot only: exchangeInfo is spot; we also skip leveraged tokens / oddballs if needed
        sym = s.get("symbol")
        if not sym:
            continue
        # Optional filter: remove UP/DOWN leveraged tokens (often not on spot, but safe)
        if sym.endswith("UPUSDT") or sym.endswith("DOWNUSDT"):
            continue
        symbols.append(sym)

    return symbols


async def get_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int
) -> pd.DataFrame:
    url = f"{BINANCE_REST}/api/v3/klines"
    data = await fetch_json(session, url, params={"symbol": symbol, "interval": interval, "limit": limit})

    if not data:
        print(f"[WARN] Klines for {symbol} {interval} unavailable; returning empty DataFrame")
        # return empty DataFrame with expected columns
        return pd.DataFrame(columns=[
            "openTime", "open", "high", "low", "close", "volume",
            "closeTime", "quoteAssetVolume", "numTrades",
            "takerBuyBaseVol", "takerBuyQuoteVol", "ignore"
        ])

    # Binance kline array format:
    # [ openTime, open, high, low, close, volume, closeTime, ... ]
    df = pd.DataFrame(data, columns=[
        "openTime", "open", "high", "low", "close", "volume",
        "closeTime", "quoteAssetVolume", "numTrades",
        "takerBuyBaseVol", "takerBuyQuoteVol", "ignore"
    ])

    # Convert to numeric
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["closeTime"] = pd.to_numeric(df["closeTime"], errors="coerce")
    df = df.dropna(subset=["close", "closeTime"])

    return df


def compute_ema100_200_from_close(close: pd.Series) -> Tuple[float, float]:
    e100 = float(ema(close, 100).iloc[-1])
    e200 = float(ema(close, 200).iloc[-1])
    return e100, e200


async def scan_symbol(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    symbol: str
) -> Optional[dict]:
    async with sem:
        # small delay to reduce API burst
        if PER_SYMBOL_DELAY_SEC > 0:
            await asyncio.sleep(PER_SYMBOL_DELAY_SEC)

        try:
            # 4H data for crossover + EMA100/200 4H
            df4h = await get_klines(session, symbol, "4h", CANDLE_LIMIT_4H)
            if df4h.empty:
                return None
            close4h = df4h["close"]
            offset = find_last_bullish_cross_offset(close4h, max_lookback=12)

            if offset is None or offset not in OFFSETS_ALLOWED:
                return None

            ema100_4h, ema200_4h = compute_ema100_200_from_close(close4h)

            # 1D EMA100/200
            df1d = await get_klines(session, symbol, "1d", CANDLE_LIMIT_1D)
            if df1d.empty:
                return None
            close1d = df1d["close"]
            ema100_1d, ema200_1d = compute_ema100_200_from_close(close1d)

            return {
                "symbol": symbol,
                "offset": offset,
                "ema100_4h": ema100_4h,
                "ema200_4h": ema200_4h,
                "ema100_1d": ema100_1d,
                "ema200_1d": ema200_1d,
                "tv_chart": tv_chart_link(symbol),
                "tv_page": tv_symbol_page(symbol),
            }

        except Exception as e:
            # Keep scan running; optionally print to logs
            print(f"[WARN] {symbol} scan failed: {e}")
            return None


def format_results_grouped(results: List[dict]) -> Tuple[str, List[str]]:
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    run_label = now_ist.strftime("%Y-%m-%d %H:%M IST")

    # Group by offset
    buckets: Dict[int, List[dict]] = {k: [] for k in sorted(OFFSETS_ALLOWED)}
    for r in results:
        buckets[r["offset"]].append(r)

    # Sort each bucket by symbol
    for k in buckets:
        buckets[k].sort(key=lambda x: x["symbol"])

    total = len(results)

    header = (
        f"EMA20↑EMA50 (4H) Screener\n"
        f"Run: {run_label}\n"
        f"Signals: {total}\n"
        f"Buckets: 0/1/2/4/5 candles ago"
    )

    lines: List[str] = []
    # "48 hrs data" = names only (bucket-wise)
    for offset in [0, 1, 2, 4, 5]:
        name = "FRESH (0)" if offset == 0 else f"{offset} candle(s) ago"
        syms = [x["symbol"] for x in buckets.get(offset, [])]
        if syms:
            lines.append(f"\n=== {name} ===")
            # names only, comma separated
            lines.append(", ".join(syms))
        else:
            lines.append(f"\n=== {name} ===")
            lines.append("(none)")

    # Then details with EMA100/200 only
    lines.append("\n--- DETAILS (EMA100/EMA200 only) ---")
    for offset in [0, 1, 2, 4, 5]:
        for r in buckets.get(offset, []):
            lines.append(
                f"\n{r['symbol']}  |  offset: {r['offset']}\n"
                f"4H  EMA100: {r['ema100_4h']:.6f}  EMA200: {r['ema200_4h']:.6f}\n"
                f"1D  EMA100: {r['ema100_1d']:.6f}  EMA200: {r['ema200_1d']:.6f}\n"
                f"TV Chart: {r['tv_chart']}\n"
                f"TV Page:  {r['tv_page']}"
            )

    return header, lines


async def telegram_send_with_retry(
    session: aiohttp.ClientSession,
    text: str,
    max_retries: int = 6
) -> bool:
    """
    Handles Telegram flood control (429) by waiting and retrying.
    Returns True if sent, False if not configured.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[INFO] Telegram not configured (missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID). Printing message:")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, max_retries + 1):
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
                data = await resp.json(content_type=None)

                if resp.status == 200 and data.get("ok") is True:
                    return True

                # Flood control
                if resp.status == 429:
                    retry_after = 5
                    params = data.get("parameters") or {}
                    if isinstance(params, dict) and params.get("retry_after"):
                        retry_after = int(params["retry_after"])
                    wait_sec = max(retry_after, 5)
                    print(f"[WARN] Telegram 429 rate limit. Waiting {wait_sec}s (attempt {attempt}/{max_retries})")
                    await asyncio.sleep(wait_sec)
                    continue

                # Other errors: show and retry with backoff
                print(f"[WARN] Telegram send failed HTTP {resp.status}: {str(data)[:300]}")
                await asyncio.sleep(min(2 ** attempt, 30))
        except Exception as e:
            print(f"[WARN] Telegram exception attempt {attempt}/{max_retries}: {e}")
            await asyncio.sleep(min(2 ** attempt, 30))

    print("[ERROR] Telegram send failed after retries.")
    return True  # configured but failed


async def send_telegram_chunked(session: aiohttp.ClientSession, header: str, lines: List[str]) -> None:
    # Always send header (heartbeat), even if no signals
    await telegram_send_with_retry(session, header)
    await asyncio.sleep(TG_BETWEEN_MSG_DELAY_SEC)

    if not lines:
        return

    # Chunk the body into safe-size messages
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > TG_CHUNK_SIZE:
            await telegram_send_with_retry(session, chunk)
            await asyncio.sleep(TG_BETWEEN_MSG_DELAY_SEC)
            chunk = line
        else:
            chunk = (chunk + "\n" + line) if chunk else line

    if chunk:
        await telegram_send_with_retry(session, chunk)
        await asyncio.sleep(TG_BETWEEN_MSG_DELAY_SEC)


async def main():
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        symbols = await get_usdt_spot_symbols(session)
        print(f"Symbols found: {len(symbols)}")

        tasks = [scan_symbol(session, sem, s) for s in symbols]
        out = await asyncio.gather(*tasks)

        results = [r for r in out if r is not None]
        print(f"Signals found: {len(results)}")

        header, lines = format_results_grouped(results)
        await send_telegram_chunked(session, header, lines)


if __name__ == "__main__":
    # If anything crashes, try to push error to Telegram too
    try:
        asyncio.run(main())
    except Exception as e:
        # best-effort Telegram error alert
        try:
            async def _send_err():
                async with aiohttp.ClientSession() as session:
                    now_ist = datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
                    msg = f"[ERROR] Screener crashed\nRun: {now_ist}\nReason: {e}"
                    await telegram_send_with_retry(session, msg)
            asyncio.run(_send_err())
        except Exception:
            pass
        raise
