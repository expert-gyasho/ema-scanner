import os
import time
import logging
import requests
import pandas as pd
from ta.trend import EMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

logging.basicConfig(level=logging.INFO)


# ---------------- SAFE API CALL ----------------
def safe_get(url):
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except Exception as e:
        logging.error(f"API Error: {e}")
        return {}


# ---------------- GET SYMBOLS ----------------
def get_symbols():
    data = safe_get(BINANCE_EXCHANGE_INFO)

    if not isinstance(data, dict):
        return []

    if "symbols" not in data:
        logging.error(f"Invalid response: {data}")
        return []

    symbols = []
    for s in data["symbols"]:
        if s.get("status") == "TRADING":
            symbols.append(s["symbol"])

    return symbols


# ---------------- GET PRICE DATA ----------------
def get_data(symbol, interval="1h"):
    params = {"symbol": symbol, "interval": interval, "limit": 100}
    data = safe_get(BINANCE_KLINES)

    if not isinstance(data, list):
        return None

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "c1", "c2", "c3", "c4", "c5", "c6"
    ])

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


# ---------------- EMA CHECK ----------------
def check_ema(df):
    if df is None or len(df) < 50:
        return "⚠️ Not enough data"

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator()

    if ema20.iloc[-2] < ema50.iloc[-2] and ema20.iloc[-1] > ema50.iloc[-1]:
        return "📈 BUY SIGNAL"

    if ema20.iloc[-2] > ema50.iloc[-2] and ema20.iloc[-1] < ema50.iloc[-1]:
        return "📉 SELL SIGNAL"

    return "NO SIGNAL"


# ---------------- TELEGRAM ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 EMA Scanner Stable Bot Started")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"
    df = get_data(symbol)

    signal = check_ema(df)

    await update.message.reply_text(
        f"{symbol}\n{signal}"
    )


# ---------------- MAIN ----------------
def main():
    if not TOKEN:
        raise Exception("BOT_TOKEN missing in environment variables")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))

    print("Bot Running Stable Version...")

    app.run_polling()


if __name__ == "__main__":
    main()
