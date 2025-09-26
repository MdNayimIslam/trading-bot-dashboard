from __future__ import annotations
import pandas as pd
from ..indicators.rsi import rsi
from ..indicators.moving_average import sma
from ..indicators.atr import atr as atr_func

def rsi_ma_signals(
    df: pd.DataFrame,
    rsi_len: int,
    ma_len: int,
    atr_len: int,
    use_atr_filter: bool,
    atr_thresh: float,
    rsi_buy_below: float,
    rsi_sell_above: float
):
    s = pd.DataFrame(index=df.index)
    s['rsi'] = rsi(df['close'], rsi_len)
    s['ma'] = sma(df['close'], ma_len)
    s['atr'] = atr_func(df, atr_len)
    s['atr_pct'] = s['atr'] / df['close']

    long = (s['rsi'] < rsi_buy_below) & (df['close'] > s['ma'])
    short = (s['rsi'] > rsi_sell_above) & (df['close'] < s['ma'])

    if use_atr_filter:
        long &= (s['atr_pct'] > atr_thresh)
        short &= (s['atr_pct'] > atr_thresh)

    signal = pd.Series(0, index=df.index)
    signal[long] = 1
    signal[short] = -1
    return signal, s