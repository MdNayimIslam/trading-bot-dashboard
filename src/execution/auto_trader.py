# ✅ AUTO TRADING BOT (Binance Live/Testnet) - Risk + Logging Added

import time, csv
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
SANDBOX    = True      # 👉 True = Testnet, False = Real trading

# === Load YAML Config ===
CONFIG_PATH = Path("config/config.yaml")
CFG   = yaml.safe_load(CONFIG_PATH.read_text()) or {}
STRAT = CFG.get("strategy", {})
RISK  = CFG.get("risk", {})

# === Risk Parameters ===
RISK_PER_TRADE = RISK.get("risk_per_trade", 0.01)   # 1% default
STOP_LOSS_PCT  = RISK.get("stop_loss_pct", 0.02)    # 2% default
TAKE_PROFIT_PCT= RISK.get("take_profit_pct", 0.04)  # 4% default

# === INIT BROKER ===
broker = LiveBroker(
    exchange_id="binance",
    api_key=API_KEY,
    secret=API_SECRET,
    sandbox=SANDBOX,
    recv_window_ms=10000,
)

# === Trade Logger ===
def log_trade(signal, price, balance, qty):
    with open("trade_log.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), signal, price, qty, balance])

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
stop_loss = None
take_profit = None

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

        # === Position Sizing (risk-based) ===
        balance = broker.fetch_balance()
        usdt_balance = float(balance.get("USDT", {}).get("free", 10000))
        trade_capital = usdt_balance * RISK_PER_TRADE
        qty = trade_capital / price

        # === TRADING LOGIC ===
        if signal == "buy" and not last_order:
            print("🟢 Buy signal detected!")
            broker.create_order(SYMBOL, "buy", "market", qty)
            last_order = "buy"
            entry_price = price
            stop_loss   = entry_price * (1 - STOP_LOSS_PCT)
            take_profit = entry_price * (1 + TAKE_PROFIT_PCT)
            print(f"✅ Buy order placed at {price} | SL={stop_loss:.2f}, TP={take_profit:.2f}")
            log_trade("BUY", price, usdt_balance, qty)

        elif signal == "sell" and last_order == "buy":
            print("🔴 Sell signal detected!")
            broker.create_order(SYMBOL, "sell", "market", qty)
            last_order = None
            entry_price = None
            stop_loss, take_profit = None, None
            print(f"✅ Sell order placed at {price}")
            log_trade("SELL", price, usdt_balance, qty)

        elif last_order == "buy":
            # === Risk Management Check ===
            if price <= stop_loss:
                print("⛔ Stop-Loss triggered!")
                broker.create_order(SYMBOL, "sell", "market", qty)
                last_order = None
                entry_price = None
                stop_loss, take_profit = None, None
                log_trade("STOP_LOSS", price, usdt_balance, qty)

            elif price >= take_profit:
                print("🎯 Take-Profit triggered!")
                broker.create_order(SYMBOL, "sell", "market", qty)
                last_order = None
                entry_price = None
                stop_loss, take_profit = None, None
                log_trade("TAKE_PROFIT", price, usdt_balance, qty)
            else:
                print("⚪ Holding position...")

        else:
            print("⚪ No trade executed this round")

        time.sleep(TIMEFRAME)

    except KeyboardInterrupt:
        print("👋 Exiting bot safely...")
        break
    except Exception as e:
        print(f"⚠️ Error: {e}")
        time.sleep(5)