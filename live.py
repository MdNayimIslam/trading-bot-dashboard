import argparse
from pathlib import Path
import yaml
import pandas as pd
import time
from datetime import datetime

from src.execution.live_broker import LiveBroker
from src.data.connectors.binance import fetch_ohlcv
from src.strategies.rsi_ma import rsi_ma_signals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.yaml", help="YAML config path")
    ap.add_argument("--symbol", default="BTC/USDT", help="Trading pair, e.g., BTC/USDT")
    ap.add_argument("--qty", type=float, default=0.001, help="Trade quantity")
    ap.add_argument("--interval", type=int, default=60, help="Seconds between checks")
    ap.add_argument("--sandbox", action="store_true", help="Enable Binance testnet sandbox")
    args = ap.parse_args()

    # === Load Config ===
    cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    strat = cfg.get("strategy", {}) or {}

    # === API Keys (Direct or .env) ===
    API_KEY = strat.get("api_key", "YOUR_API_KEY")
    API_SECRET = strat.get("api_secret", "YOUR_SECRET_KEY")

    # === Init Broker ===
    broker = LiveBroker(
        exchange_id="binance",
        api_key=API_KEY,
        secret=API_SECRET,
        sandbox=args.sandbox,
        recv_window_ms=10000,
    )
    try:
        broker._sync_time()
    except Exception as e:
        print(f"⚠️ Time sync failed: {e}")

    print(f"🚀 Live Trading Started for {args.symbol} (qty={args.qty})...\n")

    last_order = None

    while True:
        try:
            # === Fetch Price ===
            ticker = broker.fetch_ticker(args.symbol)
            price = ticker.get("last")
            if not price:
                print("⚠️ Price fetch failed. Retrying...")
                time.sleep(5)
                continue

            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📈 {args.symbol} Price: {price}")

            # === Build Indicators ===
            lookback = max(
                strat.get("ma_len", 100),
                strat.get("rsi_len", 14),
                strat.get("atr_len", 14),
            ) + 5

            ohlcv = fetch_ohlcv(args.symbol, timeframe="1m", limit=lookback)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

            sig_series, ind = rsi_ma_signals(
                df,
                strat.get("rsi_len", 14),
                strat.get("ma_len", 50),
                strat.get("atr_len", 14),
                strat.get("use_atr_filter", False),
                strat.get("atr_thresh", 0.0),
                strat.get("rsi_buy_below", 30),   # 🔧 safer
                strat.get("rsi_sell_above", 70),  # 🔧 safer
            )

            sig_val = int(sig_series.iloc[-1])
            signal = "buy" if sig_val == 1 else "sell" if sig_val == -1 else "hold"

            # === Trading Logic ===
            if signal == "buy" and last_order is None:
                print("🟢 Buy signal detected!")
                try:
                    broker.create_order(args.symbol, "buy", "market", args.qty)
                    last_order = "buy"
                    print(f"✅ Buy order placed at {price}")
                except Exception as e:
                    print(f"⚠️ Buy order failed: {e}")

            elif signal == "sell" and last_order == "buy":
                print("🔴 Sell signal detected!")
                try:
                    broker.create_order(args.symbol, "sell", "market", args.qty)
                    last_order = None
                    print(f"✅ Sell order placed at {price}")
                except Exception as e:
                    print(f"⚠️ Sell order failed: {e}")

            else:
                print("⚪ No trade signal this round")

            time.sleep(args.interval)

        except KeyboardInterrupt:
            print("👋 Exiting...")
            break
        except Exception as e:
            print(f"⚠️ Runtime Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()