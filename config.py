import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("8675841494:AAEzmnO0CdlxuAQb5GquESV8NID4IN2PIKI")
TELEGRAM_CHAT_ID = os.getenv("6816154549")
# Binance
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

# Scanner Settings
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
EMA_FAST = int(os.getenv("EMA_FAST", 20))
EMA_SLOW = int(os.getenv("EMA_SLOW", 50))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", 100000))
