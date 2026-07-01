import os
import requests
import pandas as pd
from ta.trend import EMAIndicator
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================
# CONFIG
# ==========================

TIMEFRAME = "4h"
LIMIT = 100

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BINANCE_INFO = "https://api.binance.com/api/v3/exchangeInfo"

# ==========================
# GET ALL USDT SYMBOLS
# ==========================

def get_symbols():

    data = requests.get(BINANCE_INFO, timeout=20).json()

    symbols = []

    for s in data["symbols"]:

        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
        ):
            symbols.append(s["symbol"])

    return sorted(symbols)

# ==========================
# DOWNLOAD CANDLES
# ==========================

def get_klines(symbol):

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}"
        f"&interval={TIMEFRAME}"
        f"&limit={LIMIT}"
    )

    try:

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
