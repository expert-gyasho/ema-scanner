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

session = requests.Session()

# ----------------------------
# TELEGRAM
# ----------------------------

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("Missing Telegram credentials")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=30
        )
    except Exception as e:
        print("Telegram error:", e)

# ----------------------------
# SYMBOLS (SAFE + STABLE)
# ----------------------------

def get_symbols():

    url = "https://api.binance.com/api/v3/exchangeInfo"

    for _ in range(5):

        try:
            res = session.get(url, timeout=20)
            data = res.json()

            # SAFE CHECK
            if not isinstance(data, dict):
                continue

            if "symbols" not in data:
                print("Binance response error:", data)
                continue

            return [
                s["symbol"]
                for s in data["symbols"]
                if s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
            ]

        except Exception as e:
            print("get_symbols error:", e)

    return []

# ----------------------------
# CANDLES
# ----------------------------

def get_dataframe(symbol):

    try:
        url = (
            f"https://api.binance.com/api/v3/klines?"
            f"symbol={symbol}&interval={TIMEFRAME}&limit={LIMIT}"
        )

        data = session.get(url, timeout=20).json()

        if not isinstance(data, list):
            return None

        df = pd.DataFrame(data)[[0,1,2,3,4]]
        df.columns = ["time", "open", "high", "low", "close"]

        df["close"] = df["close"].astype(float)

        return df

    except Exception as e:
        print(f"Data error {symbol}:", e)
        return None

# ----------------------------
# EMA LOGIC
# ----------------------------

def check_signal(df):

    if df is None or len(df) < 60:
        return None

    df["ema20"] = EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = EMAIndicator(df["close"], window=50).ema_indicator()

    df = df.dropna()

    if len(df) < 60:
        return None

    if df["ema20"].iloc[-1] <= df["ema50"].iloc[-1]:
        return None

    prev20, prev50 = df["ema20"].iloc[-2], df["ema50"].iloc[-2]
    curr20, curr50 = df["ema20"].iloc[-1], df["ema50"].iloc[-1]

    # Fresh cross
    if prev20 <= prev50 and curr20 > curr50:
        return "fresh"

    # Old cross (last 6 candles)
    for i in range(len(df) - 6, len(df)):
        if df["ema20"].iloc[i-1] <= df["ema50"].iloc[i-1] and df["ema20"].iloc[i] > df["ema50"].iloc[i]:
            return "old"

    return None

# ----------------------------
# SCAN COIN
# ----------------------------

def scan_coin(symbol):

    try:
        df = get_dataframe(symbol)
        signal = check_signal(df)

        if signal:
            return symbol, signal

    except Exception as e:
        print(f"scan error {symbol}:", e)

    return None

# ----------------------------
# SCAN ALL
# ----------------------------

def run_scan():

    symbols = get_symbols()

    if not symbols:
        return [], [], 0

    fresh, old = [], []

    with ThreadPoolExecutor(max_workers=10) as executor:

        futures = [executor.submit(scan_coin, s) for s in symbols]

        for f in as_completed(futures):

            result = f.result()

            if result is None:
                continue

            symbol, signal = result

            if signal == "fresh":
                fresh.append(symbol)
            elif signal == "old":
                old.append(symbol)

    return fresh, old, len(symbols)

# ----------------------------
# MESSAGE
# ----------------------------

def build_message(fresh, old, total):

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    msg = []
    msg.append("🚀 EMA20 × EMA50 Scanner\n")
    msg.append(f"📅 {now.strftime('%d-%m-%Y')}")
    msg.append(f"⏰ {now.strftime('%I:%M %p')} IST\n")

    msg.append("🔥 Fresh Cross")
    msg.append("\n".join(sorted(fresh)) if fresh else "No Fresh Cross")
    msg.append(f"Total: {len(fresh)}\n")

    msg.append("📈 Old Cross")
    msg.append("\n".join(sorted(old)) if old else "No Old Cross")
    msg.append(f"Total: {len(old)}\n")

    msg.append(f"📊 Total Scanned: {total}")
    msg.append("✅ Scan Completed")

    return "\n".join(msg)

# ----------------------------
# MAIN
# ----------------------------

def main():

    fresh, old, total = run_scan()

    message = build_message(fresh, old, total)

    print(message)
    send_telegram(message)

if __name__ == "__main__":
    main()
