import os
import logging
import requests
import pandas as pd
from ta.trend import EMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL = os.getenv("INTERVAL", "1h")

logging.basicConfig(level=logging.INFO)

BINANCE_URL = "https://api.binance.com/api/v3/klines"


def get_data(symbol, interval):
    params = {"symbol": symbol, "interval": interval, "limit": 100}
    data = requests.get(BINANCE_URL, params=params).json()

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "c1", "c2", "c3", "c4", "c5", "c6"
    ])

    df["close"] = pd.to_numeric(df["close"])
    return df


def check_ema_cross(df):
    ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator()

    if ema20.iloc[-2] < ema50.iloc[-2] and ema20.iloc[-1] > ema50.iloc[-1]:
        return "📈 BUY SIGNAL (EMA 20 crossed above EMA 50)"

    if ema20.iloc[-2] > ema50.iloc[-2] and ema20.iloc[-1] < ema50.iloc[-1]:
        return "📉 SELL SIGNAL (EMA 20 crossed below EMA 50)"

    return "NO SIGNAL"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("EMA Scanner Bot Started 🚀")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_data(SYMBOL, INTERVAL)
    signal = check_ema_cross(df)
    await update.message.reply_text(f"{SYMBOL} ({INTERVAL})\n{signal}")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
