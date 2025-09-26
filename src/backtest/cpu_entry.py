from __future__ import annotations
from ..data.loader import load_ohlcv
from ..utils.config import normalize_fee_slippage
from .engine import backtest
from ..indicators.rsi import rsi as rsi_cpu
from ..indicators.moving_average import sma as sma_cpu
from ..indicators.atr import atr as atr_cpu
import pandas as pd

def build_signals(df: pd.DataFrame, strategy: dict):
    rsi_len = int(strategy.get('rsi_len', 14))
    ma_len = int(strategy.get('ma_len', 50))
    atr_len = int(strategy.get('atr_len', 14))
    use_atr_filter = bool(strategy.get('use_atr_filter', False))
    atr_thresh = float(strategy.get('atr_thresh', 0.0))

    r = rsi_cpu(df['close'], rsi_len)
    m = sma_cpu(df['close'], ma_len)
    a = atr_cpu(df, atr_len)
    ind = pd.DataFrame({'rsi': r.values, 'ma': m.values, 'atr': a.values}, index=df.index)
    atr_pct = a / df['close']

    long = (r > 55) & (df['close'] > m)
    short = (r < 45) & (df['close'] < m)
    if use_atr_filter:
        long &= (atr_pct > atr_thresh)
        short &= (atr_pct > atr_thresh)

    signal = pd.Series(0, index=df.index, dtype='int8')
    signal[long] = 1
    signal[short] = -1
    return signal, ind

def run_once(cfg: dict, device: str = "cpu") -> dict:
    ds = cfg.get("dataset") or cfg.get("base", {}).get("dataset") or cfg.get("core", {}).get("dataset")
    if not ds:
        ds = "data/sample_BTCUSDT_1h.csv"
    df = load_ohlcv(ds, "data/sample_BTCUSDT_1h.csv")
    fees = normalize_fee_slippage(cfg.get("fees") or cfg)
    risk = cfg.get("risk", {})
    strat = cfg.get("strategy", {})

    sig, ind = build_signals(df, strat)
    eq, trades = backtest(
        df, sig, ind,
        risk.get('initial_capital', 10000.0),
        risk.get('risk_per_trade', 0.01),
        risk.get('atr_stop_mult', 0.0),
        risk.get('tp_mult', 0.0),
        fees.get('fee_pct', 0.0),
        fees.get('slippage_pct', 0.0)
    )
    # eq may be list/np/pd.Series
    try:
        final = eq.iloc[-1]
    except Exception:
        final = eq[-1] if hasattr(eq, "__getitem__") else None
    return {"equity": eq, "final_equity": final, "trades": trades}
