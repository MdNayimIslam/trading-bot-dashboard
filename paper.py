import argparse
import yaml
from pathlib import Path
import pandas as pd

from src.data.loader import load_ohlcv
from src.strategies.rsi_ma import rsi_ma_signals
from src.backtest.engine import backtest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    # Load config
    cfg = yaml.safe_load(Path(args.config).read_text())

    # Load OHLCV data
    df = load_ohlcv(args.csv, "data/sample_BTCUSDT_1h.csv")

    # Generate signals (with RSI bounds)
    signal, ind = rsi_ma_signals(
        df,
        cfg["strategy"]["rsi_len"],
        cfg["strategy"]["ma_len"],
        cfg["strategy"]["atr_len"],
        cfg["strategy"]["use_atr_filter"],
        cfg["strategy"]["atr_thresh"],
        cfg["strategy"]["rsi_buy_below"],
        cfg["strategy"]["rsi_sell_above"],
    )

    # Fix: if indicators are dict → convert to DataFrame
    if isinstance(ind, dict):
        ind = pd.DataFrame(ind)

    # Run backtest / paper trading
    eq, trades = backtest(
        df,
        signal,
        ind,
        cfg["paper"]["starting_balance"],
        cfg["risk"]["risk_per_trade"],
        cfg["risk"]["atr_stop_mult"],
        cfg["risk"]["tp_mult"],
        cfg["fees"]["fee_pct"],
        cfg["fees"]["slippage_pct"],
    )

    print("📊 Paper trading finished")
    print("Final equity:", eq.iloc[-1])
    print("Total trades:", len(trades))


if __name__ == "__main__":
    main()