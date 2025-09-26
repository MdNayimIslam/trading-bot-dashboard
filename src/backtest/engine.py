from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Tuple, Dict, Any, List

from ..risk.position_sizing import atr_position_size


# -------------------- Data classes --------------------
@dataclass
class FillParams:
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005


@dataclass
class TradeResult:
    entry_idx: int
    exit_idx: int
    side: int
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    ret: float


# -------------------- Indicators (local fallbacks) --------------------
def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Simple ATR (RMA/EMA নয়—rolling mean TR) as a safe fallback."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    prev_c = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(n, min_periods=n).mean()
    return atr.reindex(df.index)


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Classic RSI (Wilder’s) simplified."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _rsi_ma_signals_local(
    df: pd.DataFrame,
    rsi_len: int,
    ma_len: int,
    atr_len: int,
    use_atr_filter: bool = False,
    atr_thresh: float = 0.0,
    rsi_buy_below: int = 30,
    rsi_sell_above: int = 70,
) -> Tuple[pd.Series, pd.DataFrame]:
    """Local fallback for RSI+MA strategy signals."""
    close = df["close"]
    rsi = _rsi(close, rsi_len)
    ma = close.rolling(ma_len, min_periods=ma_len).mean().bfill()
    atr = _atr(df, atr_len).fillna(0.0)

    # Entry logic: buy when RSI crosses up from below threshold and price above MA; sell when crosses down.
    long_signal = (rsi.shift(1) < rsi_buy_below) & (rsi >= rsi_buy_below) & (close > ma)
    short_signal = (rsi.shift(1) > rsi_sell_above) & (rsi <= rsi_sell_above) & (close < ma)

    sig = pd.Series(0, index=df.index, dtype=int)
    sig[long_signal] = 1
    sig[short_signal] = -1

    if use_atr_filter and atr_thresh > 0:
        vol_ok = (atr / close).fillna(0.0) >= atr_thresh
        sig = sig.where(vol_ok, 0)

    ind = pd.DataFrame({"rsi": rsi, "ma": ma, "atr": atr}, index=df.index)
    return sig, ind


# -------------------- Core backtest (your original logic) --------------------
def backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    ind: pd.DataFrame,
    initial_capital: float,
    risk_per_trade: float,
    atr_stop_mult: float,
    tp_mult: float,
    fee_pct: float,
    slippage_pct: float,
) -> Tuple[pd.Series, List[TradeResult]]:
    balance = initial_capital
    equity_curve: List[float] = []
    position = None
    trades: List[TradeResult] = []

    price = df["close"].values
    atr = ind["atr"].values if "atr" in ind.columns else np.zeros(len(df))

    for i in range(len(df)):
        p = float(price[i])

        # mark-to-market equity
        if position is not None:
            side = position["side"]
            entry = position["entry_price"]
            qty = position["qty"]
            mtm = (p - entry) * qty * side
            equity_curve.append(balance + mtm)
        else:
            equity_curve.append(balance)

        # exit logic
        if position is not None:
            side = position["side"]
            qty = position["qty"]
            stop = position["stop"]
            tp = position["tp"]
            entry_idx = position["entry_idx"]
            exit_reason = None
            if (side == 1 and p <= stop) or (side == -1 and p >= stop):
                exit_reason = "stop"
            elif (side == 1 and p >= tp) or (side == -1 and p <= tp):
                exit_reason = "tp"

            if exit_reason:
                exit_price = p * (1 - slippage_pct) if side == 1 else p * (1 + slippage_pct)
                fee = (abs(qty) * exit_price) * fee_pct
                entry_price_net = position["entry_price_net"]
                pnl = (exit_price - entry_price_net) * qty * side - fee
                balance += pnl
                # ret: PnL as fraction of balance AFTER close would distort; keep vs initial or entry equity
                ret = pnl / max(1e-9, initial_capital)
                trades.append(
                    TradeResult(entry_idx, i, side, position["entry_price"], exit_price, qty, float(pnl), float(ret))
                )
                position = None

        # entry logic
        if position is None and int(signal.iloc[i]) != 0:
            side = int(signal.iloc[i])
            a = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            if a <= 0:
                continue
            qty = atr_position_size(balance, risk_per_trade, a, p, atr_stop_mult)
            if qty <= 0:
                continue

            entry_price = p * (1 + slippage_pct) if side == 1 else p * (1 - slippage_pct)
            fee = (abs(qty) * entry_price) * fee_pct
            # Make entry_price_net the cash-equivalent break-even price per unit
            entry_price_net = entry_price + (fee / max(1e-9, abs(qty))) * (1 if side == 1 else -1)
            stop = entry_price - side * (a * atr_stop_mult)
            tp = entry_price + side * (a * atr_stop_mult * tp_mult)
            position = {
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "entry_price_net": entry_price_net,
                "stop": stop,
                "tp": tp,
                "entry_idx": i,
            }

    eq = pd.Series(equity_curve, index=df.index, name="equity")
    return eq, trades


# -------------------- Compatibility shim (robust) --------------------
def backtest_prices(prices: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts:
      - pandas.DataFrame with OHLC[V] (preferred),
      - pandas.Series/np.ndarray of close prices,
      - any object with .values (1D).
    Uses cfg['strategy'] & cfg['risk'] and returns dict: {'equity','final_equity','trades'}.
    """
    # --- Normalize to DataFrame with close/high/low/volume ---
    df: pd.DataFrame
    if isinstance(prices, pd.DataFrame):
        df = prices.copy()

        # ensure close exists or pick a sensible column
        if "close" not in df.columns:
            for col in ["Close", "close_price", "c", "ClosePrice", "CLOSE"]:
                if col in df.columns:
                    df["close"] = df[col]
                    break
        # if still no close, take first numeric column
        if "close" not in df.columns:
            num = df.select_dtypes(include="number")
            if num.shape[1] == 0:
                raise ValueError("No numeric close-like column found in DataFrame")
            df["close"] = num.iloc[:, 0]

        # fill missing ohlc if needed
        for col in ["open", "high", "low"]:
            if col not in df.columns:
                df[col] = df["close"]
        if "volume" not in df.columns:
            df["volume"] = 0.0

    else:
        # 1D input → synth OHLCV
        c = getattr(prices, "values", prices)
        c = np.asarray(c, dtype=float)
        idx = pd.RangeIndex(len(c))
        df = pd.DataFrame(
            {"open": c, "high": c, "low": c, "close": c, "volume": np.zeros_like(c)}, index=idx
        )

    # --- Read config (with safe defaults) ---
    strategy = dict(cfg.get("strategy") or {})
    risk = dict(cfg.get("risk") or {})

    rsi_len = int(strategy.get("rsi_len", 14))
    ma_len = int(strategy.get("ma_len", 50))
    atr_len = int(strategy.get("atr_len", 14))
    use_atr_filter = bool(strategy.get("use_atr_filter", False))
    atr_thresh = float(strategy.get("atr_thresh", 0.0))
    rsi_buy_below = int(strategy.get("rsi_buy_below", 30))
    rsi_sell_above = int(strategy.get("rsi_sell_above", 70))

    initial_capital = float(risk.get("initial_capital", 10000.0))
    risk_per_trade = float(risk.get("risk_per_trade", 0.01))
    atr_stop_mult = float(strategy.get("atr_stop_mult", 2.0))
    tp_mult = float(strategy.get("tp_mult", 2.0))
    fee_pct = float(risk.get("fee_pct", 0.0))
    slippage_pct = float(risk.get("slippage_pct", 0.0))

    # --- Build signals (prefer official strategy if present) ---
    try:
        # If your repo exposes the official function, prefer it
        from ..strategies.rsi_ma import rsi_ma_signals as official_sig

        sig, ind = official_sig(
            df,
            rsi_len,
            ma_len,
            atr_len,
            use_atr_filter,
            atr_thresh,
            rsi_buy_below=rsi_buy_below,
            rsi_sell_above=rsi_sell_above,
        )
        # Ensure 'atr' exists (some implementations might name differently)
        if isinstance(ind, dict):
            ind = pd.DataFrame(ind, index=df.index)
        if "atr" not in ind.columns:
            ind["atr"] = _atr(df, atr_len).fillna(0.0)
    except Exception:
        # Local fallback
        sig, ind = _rsi_ma_signals_local(
            df,
            rsi_len=rsi_len,
            ma_len=ma_len,
            atr_len=atr_len,
            use_atr_filter=use_atr_filter,
            atr_thresh=atr_thresh,
            rsi_buy_below=rsi_buy_below,
            rsi_sell_above=rsi_sell_above,
        )

    # --- Run core backtest ---
    equity, trades = backtest(
        df=df,
        signal=sig,
        ind=ind,
        initial_capital=initial_capital,
        risk_per_trade=risk_per_trade,
        atr_stop_mult=atr_stop_mult,
        tp_mult=tp_mult,
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
    )

    out = {
        "equity": equity.tolist(),
        "final_equity": float(equity.iloc[-1]) if len(equity) else float(initial_capital),
        "trades": trades,
    }
    return out


# -------------------- Backward-compatible wrapper --------------------
def run_backtest(cfg, *args, **kwargs):
    """Backward-compatible wrapper that forwards to backtest (kept for old callers)."""
    return backtest(cfg, *args, **kwargs)