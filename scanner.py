import requests
import pandas as pd

# Apne Telegram bot token aur chat ID yahan se handle karein
# (Aapka custom script inko set karega)
def send_telegram_message(message):
    # Ye function aapke custom implementation ke liye hai
    pass

def fetch_ohlcv(symbol):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit=50'
    response = requests.get(url)
    data = response.json()
    df = pd.DataFrame(data, columns=[
        'Open Time', 'Open', 'High', 'Low', 'Close', 'Volume', 
        'Close Time', 'Quote Asset Volume', 'Number of Trades', 
        'Taker buy base asset volume', 'Taker buy quote asset volume', 'Ignore'
    ])
    df['Close'] = pd.to_numeric(df['Close'])
    df['Open Time'] = pd.to_datetime(df['Open Time'], unit='ms')
    return df

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def get_symbols():
    url = 'https://api.binance.com/api/v3/exchangeInfo'
    data = requests.get(url).json()
    symbols = [s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')]
    return symbols

def analyze_symbol(symbol):
    df = fetch_ohlcv(symbol)
    if len(df) < 50:
        return
    closes = df['Close']
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema100 = calculate_ema(closes, 100)
    ema200 = calculate_ema(closes, 200)

    # Cross over detection (latest)
    if ema20.iloc[-2] < ema50.iloc[-2] and ema20.iloc[-1] > ema50.iloc[-1]:
        message = f'Bullish crossover detected on {symbol} (EMA20 crossed above EMA50)'
        send_telegram_message(message)

    # Show EMA 100 and EMA 200
    print(f'{symbol} EMA100: {ema100.iloc[-1]:.2f}, EMA200: {ema200.iloc[-1]:.2f}')

def main():
    symbols = get_symbols()
    for symbol in symbols:
        analyze_symbol(symbol)

if __name__ == "__main__":
    main()
