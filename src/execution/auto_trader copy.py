# ✅ AUTO TRADING BOT (Binance Live/Testnet) - Full Logging

import time
from datetime import datetime
from pathlib import Path
import yaml
import pandas as pd

from src.execution.live_broker import LiveBroker
from src.data.connectors.binance import fetch_ohlcv
from src.strategies.rsi_ma import rsi_ma_signals

# === DIRECT API KEYS (replace with your own if needed) ===
API_KEY    = "6BAeBiPTQ2fFsGNCVsd3hro8B36DNCPINeUcwH4W72mLFPuY5JkJHuLEpazdI9h8"
API_SECRET = "GJF88UH661L5rjEy5F0DIgaSbl3WSpK4YeNSTARuXPcXSaGCx6vrILe1zgY8wOUB"

# === SETTINGS ===
SYMBOL     = "BTC/USDT"
TIMEFRAME  = 60        # seconds between checks
QUANTITY   = 0.001     # amount per trade
SANDBOX    = True      # 👉 True = Testnet, False = Real trading

# === Load YAML Config ===
CONFIG_PATH = Path("config/config.yaml")
CFG   = yaml.safe_load(CONFIG_PATH.read_text()) or {}
STRAT = CFG.get("strategy", {})

# === INIT BROKER ===
broker = LiveBroker(
    exchange_id="binance",
    api_key=API_KEY,
    secret=API_SECRET,
    sandbox=SANDBOX,
    recv_window_ms=10000,
)

# Sync time (avoid timestamp errors)
try:
    broker._sync_time()
except Exception as e:
    print(f"⚠️ Time sync failed: {e}")

# Validate API Key (fetch balance once at start)
try:
    bal = broker.fetch_balance()
    print("✅ API Key OK. Starting balance snapshot:")
    print(bal)
except Exception as e:
    print(f"❌ API Key error: {e}")

last_order = None
entry_price = None

print(f"🚀 Auto Trading Bot Started for {SYMBOL}...\n")

while True:
    try:
        # === PRICE TICK ===
        ticker = broker.fetch_ticker(SYMBOL)
        price = ticker["last"]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📈 {SYMBOL} Price: {price}")

        # === SIGNAL GENERATION ===
        lookback = max(
            STRAT.get("ma_len", 100),
            STRAT.get("rsi_len", 14),
            STRAT.get("atr_len", 14)
        ) + 5
        ohlcv = fetch_ohlcv(SYMBOL, timeframe="1m", limit=lookback)
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])

        sig_series, ind = rsi_ma_signals(
            df,
            STRAT.get("rsi_len", 14),
            STRAT.get("ma_len", 50),
            STRAT.get("atr_len", 14),
            STRAT.get("use_atr_filter", False),
            STRAT.get("atr_thresh", 0.0),
            STRAT.get("rsi_buy_below", 20),
            STRAT.get("rsi_sell_above", 75),
        )

        sig_val = int(sig_series.iloc[-1])
        signal = "buy" if sig_val == 1 else "sell" if sig_val == -1 else "hold"

        print(f"📊 Signal: {signal.upper()} | Last RSI={ind['rsi'].iloc[-1]:.2f}")

        # === TRADING LOGIC ===
        if signal == "buy" and not last_order:
            print("🟢 Buy signal detected!")
            order = broker.create_order(SYMBOL, "buy", "market", QUANTITY)
            last_order = "buy"
            entry_price = price
            print(f"✅ Buy order placed at {price}")
            print("📊 Updated Balance:", broker.fetch_balance())

        elif signal == "sell" and last_order == "buy":
            print("🔴 Sell signal detected!")
            order = broker.create_order(SYMBOL, "sell", "market", QUANTITY)
            last_order = None
            entry_price = None
            print(f"✅ Sell order placed at {price}")
            print("📊 Updated Balance:", broker.fetch_balance())

        else:
            print("⚪ No trade executed this round")

        time.sleep(TIMEFRAME)

    except KeyboardInterrupt:
        print("👋 Exiting bot safely...")
        break
    except Exception as e:
        print(f"⚠️ Error: {e}")
        time.sleep(5)