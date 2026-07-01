import os
import requests
import pandas as pd
from ta.trend import EMAIndicator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

# ----------------------------
# CONFIG
# ----------------------------

TIMEFRAME = "4h"
LIMIT = 100

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ----------------------------
# TELEGRAM
# ----------------------------

def send_telegram(message):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=30
    )

# ----------------------------
# SYMBOL LIST
# ----------------------------

import requests
import time

def get_symbols():

    url = "https://api.binance.com/api/v3/exchangeInfo"

    session = requests.Session()

    for attempt in range(3):  # retry system
        try:
            response = session.get(url, timeout=20)
            data = response.json()

            # ✅ SAFE CHECK (THIS FIXES YOUR ERROR)
            if not isinstance(data, dict) or "symbols" not in data:
                print(f"Binance API warning (attempt {attempt+1}):", data)
                time.sleep(2)
                continue

            symbols = [
                s["symbol"]
                for s in data["symbols"]
                if s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
            ]

            return symbols

        except Exception as e:
            print(f"get_symbols error (attempt {attempt+1}):", e)
            time.sleep(2)

    # If all fails → safe fallback
    return []

    url = "https://api.binance.com/api/v3/exchangeInfo"

    data = requests.get(url, timeout=20).json()

    symbols = []

    for s in data["symbols"]:

        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
        ):

            symbols.append(s["symbol"])

    return symbols

# ----------------------------
# DOWNLOAD CANDLES
# ----------------------------

def get_dataframe(symbol):

    try:

        url = (
            f"https://api.binance.com/api/v3/klines?"
            f"symbol={symbol}"
            f"&interval={TIMEFRAME}"
            f"&limit={LIMIT}"
        )

        data = requests.get(url, timeout=20).json()

        df = pd.DataFrame(data)

        df = df[[0,1,2,3,4]]

        df.columns = [
            "time",
            "open",
            "high",
            "low",
            "close"
        ]

        df["close"] = df["close"].astype(float)

        return df

    except:

        return None
        # ----------------------------
# EMA CHECK
# ----------------------------

def check_signal(df):

    if df is None:
        return None

    if len(df) < 60:
        return None

    df["ema20"] = EMAIndicator(
        close=df["close"],
        window=20
    ).ema_indicator()

    df["ema50"] = EMAIndicator(
        close=df["close"],
        window=50
    ).ema_indicator()

    # Current EMA20 must be above EMA50

    if df["ema20"].iloc[-1] <= df["ema50"].iloc[-1]:
        return None

    # ============================
    # Fresh Cross (Last Closed Candle)
    # ============================

    prev20 = df["ema20"].iloc[-2]
    prev50 = df["ema50"].iloc[-2]

    curr20 = df["ema20"].iloc[-1]
    curr50 = df["ema50"].iloc[-1]

    if prev20 <= prev50 and curr20 > curr50:
        return "fresh"

    # ============================
    # Old Cross (Last 24 Hours)
    # 6 Closed Candles
    # ============================

    for i in range(-6, -1):

        p20 = df["ema20"].iloc[i - 1]
        p50 = df["ema50"].iloc[i - 1]

        c20 = df["ema20"].iloc[i]
        c50 = df["ema50"].iloc[i]

        if p20 <= p50 and c20 > c50:
            return "old"

    return None


# ----------------------------
# SCAN SINGLE COIN
# ----------------------------

def scan_coin(symbol):

    try:

        df = get_dataframe(symbol)

        signal = check_signal(df)

        if signal is None:
            return None

        return (
            symbol,
            signal
        )

    except Exception:

        return None
        # ----------------------------
# SCAN ALL SYMBOLS
# ----------------------------

def run_scan():

    symbols = get_symbols()

    fresh = []
    old = []

    total = len(symbols)

    with ThreadPoolExecutor(max_workers=20) as executor:

        futures = {
            executor.submit(scan_coin, symbol): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            result = future.result()

            if result is None:
                continue

            symbol, signal = result

            if signal == "fresh":
                fresh.append(symbol)

            elif signal == "old":
                old.append(symbol)

    return fresh, old, total


# ----------------------------
# MESSAGE FORMAT
# ----------------------------

def build_message(fresh, old, total):

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    message = ""

    message += "🚀 EMA20 × EMA50 Scanner\n\n"

    message += f"📅 {now.strftime('%d-%m-%Y')}\n"
    message += f"⏰ {now.strftime('%I:%M %p')} IST\n\n"

    message += "=====================\n"
    message += "🔥 Fresh Cross (4 Hours)\n"
    message += "=====================\n\n"

    if fresh:

        for coin in sorted(fresh):
            message += coin + "\n"

    else:

        message += "No Fresh Cross\n"

    message += f"\nTotal : {len(fresh)}\n\n"

    message += "=====================\n"
    message += "📈 Old Cross (24 Hours)\n"
    message += "=====================\n\n"

    if old:

        for coin in sorted(old):
            message += coin + "\n"

    else:

        message += "No Old Cross\n"

    message += f"\nTotal : {len(old)}\n\n"

    message += "=====================\n"
    message += f"📊 Total Coins Scanned : {total}\n"
    message += "\n✅ Scan Completed"

    return message


# ----------------------------
# MAIN
# ----------------------------

def main():

    fresh, old, total = run_scan()

    message = build_message(
        fresh,
        old,
        total
    )

    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
