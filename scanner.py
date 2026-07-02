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

# Telegram from ENV (recommended). Do NOT hardcode in GitHub.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "10"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
PER_SYMBOL_DELAY_SEC = float(os.getenv("PER_SYMBOL_DELAY_SEC", "0.02"))

# Scan logic
TF_4H = "4h"
TF_1D = "1d"
LOOKBACK_4H_FOR_CONTEXT = 12        # 48 hours = 12 candles on 4h
FETCH_4H_CANDLES = 260              # enough for EMA200 stability
FETCH_1D_CANDLES = 260              # enough for EMA200 stability

ALLOWED_CANDLES_AGO = {0, 1, 2, 4, 5}

# Telegram constraints
TG_MAX_LEN = 3900  # keep under 4096 with margin


def tv_chart_link(symbol: str) -> str:
    # Best universal TradingView chart link (often opens in app if "supported links" enabled)
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None) -> dict:
    params = params or {}
    async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as resp:
        # Binance sometimes returns JSON error payloads with non-200 too
        try:
            data = await resp.json()
        except Exception as e:
            text = await resp.text()
            raise RuntimeError(f"Non-JSON response: HTTP {resp.status}, body={text[:200]}, error={e}")
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}: {data}")
        return data


async def fetch_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = f"{BINANCE_REST}/api/v3/klines"
    data = await fetch_json(session, url, params={"symbol": symbol, "interval": interval, "limit": limit})

    # Binance kline: [ openTime, open, high, low, close, volume, closeTime, ...]
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "tbbav", "tbqav", "ignore"
    ])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


async def get_usdt_spot_symbols(session: aiohttp.ClientSession) -> List[str]:
    url = f"{BINANCE_REST}/api/v3/exchangeInfo"
    data = await fetch_json(session, url)

    # Add defensive check for 'symbols' key
    if "symbols" not in data:
        print(f"[ERROR] 'symbols' key missing in exchangeInfo response. Available keys: {data.keys()}")
        print(f"[ERROR] Full response: {data}")
        return []

    syms = []
    for s in data.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("isSpotTradingAllowed") is False:
            continue
        # USDT quote only
        if s.get("quoteAsset") != "USDT":
            continue
        # ignore leveraged tokens etc if you want; keeping all by default
        syms.append(s["symbol"])
    return sorted(set(syms))


def find_last_bullish_cross_ago(df: pd.DataFrame) -> Optional[int]:
    """
    Returns candles_ago (0 means just-closed candle) if last bullish cross is within last LOOKBACK_4H_FOR_CONTEXT candles.
    Otherwise returns None.
    """
    if len(df) < 60:
        return None

    close = df["close"]
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)

    # Cross up when previously ema20 <= ema50 AND now ema20 > ema50
    prev = (ema20.shift(1) <= ema50.shift(1))
    now = (ema20 > ema50)
    cross = (prev & now).fillna(False)

    # Only look in last 48h window (12 candles of 4h)
    window = cross.iloc[-LOOKBACK_4H_FOR_CONTEXT:]
    if not window.any():
        return None

    # Find most recent True
    last_idx_in_window = window[window].index[-1]  # index in full df
    candles_ago = (len(df) - 1) - last_idx_in_window
    return int(candles_ago)


def calc_ema100_200(df: pd.DataFrame) -> Optional[Tuple[float, float]]:
    if len(df) < 210:
        return None
    close = df["close"]
    e100 = float(_ema(close, 100).iloc[-1])
    e200 = float(_ema(close, 200).iloc[-1])
    return e100, e200


async def send_telegram(session: aiohttp.ClientSession, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        # No secrets set => just print
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }

    async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as resp:
        data = await resp.json()
        if resp.status != 200 or not data.get("ok"):
            raise RuntimeError(f"Telegram send failed: HTTP {resp.status}, resp={data}")


async def send_telegram_chunked(session: aiohttp.ClientSession, header: str, lines: List[str]) -> None:
    """
    Unlimited output, but chunked into multiple Telegram messages safely.
    """
    chunk = header.strip()
    if not chunk:
        chunk = " "

    for line in lines:
        # +1 for newline
        if len(chunk) + 1 + len(line) > TG_MAX_LEN:
            await send_telegram(session, chunk)
            chunk = line
        else:
            chunk = f"{chunk}\n{line}"

    if chunk.strip():
        await send_telegram(session, chunk)


async def scan_symbol(session: aiohttp.ClientSession, sem: asyncio.Semaphore, symbol: str) -> Optional[Dict]:
    async with sem:
        try:
            # small pacing to avoid bursts
            if PER_SYMBOL_DELAY_SEC > 0:
                await asyncio.sleep(PER_SYMBOL_DELAY_SEC)

            df4 = await fetch_klines(session, symbol, TF_4H, FETCH_4H_CANDLES)
            ago = find_last_bullish_cross_ago(df4)
            if ago is None or ago not in ALLOWED_CANDLES_AGO:
                return None

            ema4 = calc_ema100_200(df4)
            if ema4 is None:
                return None

            df1 = await fetch_klines(session, symbol, TF_1D, FETCH_1D_CANDLES)
            ema1 = calc_ema100_200(df1)
            if ema1 is None:
                return None

            return {
                "symbol": symbol,
                "ago": ago,
                "ema4_100": ema4[0],
                "ema4_200": ema4[1],
                "ema1_100": ema1[0],
                "ema1_200": ema1[1],
                "tv": tv_chart_link(symbol),
            }
        except Exception as e:
            # keep scanning; log error
            print(f"[WARN] {symbol}: {e}")
            return None


def format_results_grouped(results: List[Dict]) -> Tuple[str, List[str]]:
    now_ist = datetime.now(IST)
    ts = now_ist.strftime("%Y-%m-%d %H:%M IST")

    grouped: Dict[int, List[Dict]] = {k: [] for k in sorted(ALLOWED_CANDLES_AGO)}
    for r in results:
        grouped[r["ago"]].append(r)

    # Header (one-liner, then groups)
    header = f"Binance USDT Spot • EMA20↑EMA50 (4H) • {ts}"

    lines: List[str] = []
    for ago in sorted(ALLOWED_CANDLES_AGO):
        items = sorted(grouped[ago], key=lambda x: x["symbol"])
        if not items:
            continue

        if ago == 0:
            lines.append("")
            lines.append("FRESH (0 candle ago):")
        else:
            lines.append("")
            lines.append(f"{ago} candle(s) ago:")

        # "48hrs data: only names" => here we show only coin name + required EMA100/200 values (4H & 1D)
        for r in items:
            sym = r["symbol"]
            lines.append(
                f"- {sym} | 4H EMA100={r['ema4_100']:.6g}, EMA200={r['ema4_200']:.6g} "
                f"| 1D EMA100={r['ema1_100']:.6g}, EMA200={r['ema1_200']:.6g}"
            )
            lines.append(f"  TV: {r['tv']}")

    if not results:
        lines = ["", "No signals in 0/1/2/4/5 candles ago within last 48h window."]

    return header, lines


async def main():
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        symbols = await get_usdt_spot_symbols(session)
        print(f"Symbols found: {len(symbols)}")

        tasks = [scan_symbol(session, sem, s) for s in symbols]
        out = await asyncio.gather(*tasks)

        results = [r for r in out if r is not None]
        print(f"Signals found: {len(results)}")

        header, lines = format_results_grouped(results)

        # Unlimited: send in chunks
        await send_telegram_chunked(session, header, lines)


if __name__ == "__main__":
    asyncio.run(main())
