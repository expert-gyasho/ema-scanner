import ccxt
import pandas as pd

exchange = ccxt.binance({
    "enableRateLimit": True,
})


def get_ohlcv(symbol, timeframe="4h", limit=200):
    """
    Download OHLCV data from Binance
    """

    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit
    )

    df = pd.DataFrame(
        candles,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    return df
