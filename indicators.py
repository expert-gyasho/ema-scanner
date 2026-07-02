import pandas as pd


def add_ema(df, ema_fast=20, ema_slow=50):
    """
    Add EMA columns to dataframe.
    """

    df["ema_fast"] = df["close"].ewm(
        span=ema_fast,
        adjust=False
    ).mean()

    df["ema_slow"] = df["close"].ewm(
        span=ema_slow,
        adjust=False
    ).mean()

    return df


def is_golden_cross(df):
    """
    Returns True if EMA Fast crossed above EMA Slow
    on the latest closed candle.
    """

    if len(df) < 60:
        return False

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    return (
        prev["ema_fast"] <= prev["ema_slow"]
        and
        curr["ema_fast"] > curr["ema_slow"]
    )


def volume_confirmed(df, multiplier=1.5):
    """
    Check whether latest volume is higher than
    average volume.
    """

    if len(df) < 30:
        return False

    avg_volume = df["volume"].tail(20).mean()
    latest_volume = df.iloc[-1]["volume"]

    return latest_volume >= avg_volume * multiplier
