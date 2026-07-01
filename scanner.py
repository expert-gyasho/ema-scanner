import os
import logging
import requests
import pandas as pd
from ta.trend import EMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


# ---------------- SAFE API ----------------
def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json()
    except Exception as e:
        logging.error(f"API Error: {e}")
        return None


# ---------------- GET DATA (4H ONLY) ----------------
def get_data(symbol="BTCUSDT"):
    params = {
        "symbol": symbol,
        "interval": "4h",
        "limit": 200
    }

    data = safe_get(BINANCE_KLINES_URL, params)

    if not isinstance(data, list):
        return None

    if len(data) < 60:
        return None

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "c1", "c2", "c3", "c4", "c5", "c6"
    ])

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna()

    if len(df) < 60:
        return None

    return df


# ---------------- EMA STRATEGY ----------------
def check_ema(df):
    if df is None:
        return "⚠️ Not enough data"

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator()

    if ema20.iloc[-2] < ema50.iloc[-2] and ema20.iloc[-1] > ema50.iloc[-1]:
        return "📈 BUY SIGNAL (4H EMA 20 crossed above EMA 50)"

    if ema20.iloc[-2] > ema50.iloc[-2] and ema20.iloc[-1] < ema50.iloc[-1]:
        return "📉 SELL SIGNAL (4H EMA 20 crossed below EMA 50)"

    return "NO SIGNAL"


# ---------------- TELEGRAM HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 4H EMA Scanner Bot Started")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"

    df = get_data(symbol)
    signal = check_ema(df)

    await update.message.reply_text(
        f"📊 {symbol} (4H)\n{signal}"
    )


# ---------------- MAIN ----------------
def main():
    if not TOKEN:
        raise Exception("BOT_TOKEN missing in environment variables")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))

    print("🚀 4H EMA Scanner Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
