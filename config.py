import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Binance
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

# Scanner Settings
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
EMA_FAST = int(os.getenv("EMA_FAST", 20))
EMA_SLOW = int(os.getenv("EMA_SLOW", 50))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", 100000))
