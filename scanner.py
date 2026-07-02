import os
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt

from config import (
    TIMEFRAME,
    EMA_FAST,
    EMA_SLOW,
)

from exchange import get_ohlcv
from indicators import (
    add_ema,
    is_golden_cross,
    volume_confirmed,
)
from telegram_bot import send_message


SIGNAL_FILE = "data/signals.json"

IST = ZoneInfo("Asia/Kolkata")


# ==========================
# Signal File
# ==========================

def load_signals():

    if not os.path.exists(SIGNAL_FILE):
        return {}

    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f)

    except:
        return {}


def save_signals(data):

    os.makedirs("data", exist_ok=True)

    with open(SIGNAL_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ==========================
# Binance
# ==========================

exchange = ccxt.binance({
    "enableRateLimit": True,
})


def get_all_usdt_pairs():

    markets = exchange.load_markets()

    pairs = []

    for symbol, market in markets.items():

        if not market["spot"]:
            continue

        if market["quote"] != "USDT":
            continue

        if market["active"] is False:
            continue

        pairs.append(symbol)

    pairs.sort()

    return pairs


# ==========================
# EMA Helper
# ==========================

def prepare_dataframe(symbol):

    df = get_ohlcv(
        symbol,
        timeframe=TIMEFRAME,
        limit=250
    )

    df = add_ema(
        df,
        EMA_FAST,
        EMA_SLOW
    )

    df["ema100"] = df["close"].ewm(
        span=100,
        adjust=False
    ).mean()

    df["ema200"] = df["close"].ewm(
        span=200,
        adjust=False
    ).mean()

    return df


def prepare_daily(symbol):

    df = get_ohlcv(
        symbol,
        timeframe="1d",
        limit=250
    )

    df["ema100"] = df["close"].ewm(
        span=100,
        adjust=False
    ).mean()

    df["ema200"] = df["close"].ewm(
        span=200,
        adjust=False
    ).mean()

    return df
