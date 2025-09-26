# ==============================================================
# 📊 Auto Trading Bot Dashboard (Streamlit + Binance + RSI-MA)
# ==============================================================

import streamlit as st
import pandas as pd
import sqlite3
import time
import yaml
import copy

from datetime import datetime
from pathlib import Path
import plotly.graph_objects as go

# === Local Imports ===
from src.execution.live_broker import LiveBroker
from src.data.connectors.binance import fetch_ohlcv
from src.strategies.rsi_ma import rsi_ma_signals


# ==============================================================
# 🔧 Load Configuration
# ==============================================================
CONFIG_PATH = Path("config/config.yaml")
CFG = yaml.safe_load(CONFIG_PATH.read_text())
DEFAULT_CFG = copy.deepcopy(CFG)   # Backup for reset

STRAT     = CFG["strategy"]
TRADE_CFG = CFG["trade"]
RISK_CFG  = CFG["risk"]
API_CFG   = CFG["api"]

API_KEY    = API_CFG["key"]
API_SECRET = API_CFG["secret"]
SANDBOX    = API_CFG["sandbox"]
SYMBOL     = API_CFG["symbol"]


# ==============================================================
# 🤝 Initialize Broker
# ==============================================================
broker = LiveBroker(
    exchange_id="binance",
    api_key=API_KEY,
    secret=API_SECRET,
    sandbox=SANDBOX,
    recv_window_ms=10_000,
)


# ==============================================================
# 🗄️ Setup Database
# ==============================================================
conn = sqlite3.connect("trades.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    time     TEXT,
    symbol   TEXT,
    signal   TEXT,
    price    REAL,
    qty      REAL,
    balance  REAL,
    rsi      REAL,
    pnl      REAL
)
""")
conn.commit()


# ==============================================================
# 🎨 Streamlit Page Config & Styling
# ==============================================================
st.set_page_config(page_title="Auto Trading Bot Dashboard", layout="wide")
st.markdown("<h1 style='text-align:center;'>📊 Auto Trading Dashboard</h1>", unsafe_allow_html=True)

# Custom CSS
st.markdown("""
    <style>
    .status-box {
        margin-top: 12px;
        padding: 10px;
        border-radius: 8px;
        font-weight: bold;
    }
    .stMetric {
        background: #fff;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }
    .block-container {padding-top: 5rem !important;}
    h1 {margin-top:0rem !important;margin-bottom:1rem !important;}
    </style>
""", unsafe_allow_html=True)


# ==============================================================
# 🧭 Sidebar Config Editor
# ==============================================================
st.sidebar.header("⚙️ Config Editor")

# === Preset Buttons ===
if st.sidebar.button("🟢 Safe Preset"):
    STRAT["rsi_buy_below"]  = 25
    STRAT["rsi_sell_above"] = 75
    TRADE_CFG["stop_loss_pct"] = 0.03
    TRADE_CFG["take_profit_pct"] = 0.06
    st.sidebar.success("Safe Preset Applied ✅")

if st.sidebar.button("🟡 Balanced Preset"):
    STRAT["rsi_buy_below"]  = 30
    STRAT["rsi_sell_above"] = 70
    TRADE_CFG["stop_loss_pct"] = 0.05
    TRADE_CFG["take_profit_pct"] = 0.10
    st.sidebar.success("Balanced Preset Applied ✅")

if st.sidebar.button("🔴 Aggressive Preset"):
    STRAT["rsi_buy_below"]  = 45
    STRAT["rsi_sell_above"] = 55
    TRADE_CFG["stop_loss_pct"] = 0.08
    TRADE_CFG["take_profit_pct"] = 0.20
    st.sidebar.success("Aggressive Preset Applied ✅")

# === Manual Editor ===
API_CFG["symbol"] = st.sidebar.selectbox(
    "Trading Pair",
    ["BTC/USDT", "ETH/USDT", "ETH/BTC", "SOL/USDT"],
    index=["BTC/USDT", "ETH/USDT", "ETH/BTC", "SOL/USDT"].index(API_CFG["symbol"])
)

STRAT["rsi_buy_below"] = st.sidebar.slider(
    "RSI Buy Below", min_value=10, max_value=50,
    value=STRAT["rsi_buy_below"]
)
STRAT["rsi_sell_above"] = st.sidebar.slider(
    "RSI Sell Above", min_value=50, max_value=90,
    value=STRAT["rsi_sell_above"]
)

TRADE_CFG["quantity"] = st.sidebar.number_input(
    "Trade Quantity", min_value=0.0001,
    value=float(TRADE_CFG["quantity"]), step=0.0001
)

TRADE_CFG["stop_loss_pct"] = st.sidebar.number_input(
    "Stop Loss %", min_value=0.005, max_value=0.2,
    value=float(TRADE_CFG["stop_loss_pct"]), step=0.005, format="%.3f"
)
TRADE_CFG["take_profit_pct"] = st.sidebar.number_input(
    "Take Profit %", min_value=0.01, max_value=0.5,
    value=float(TRADE_CFG["take_profit_pct"]), step=0.01, format="%.3f"
)

# Reset button
if st.sidebar.button("🔄 Reset to Default"):
    STRAT.update(DEFAULT_CFG["strategy"])
    TRADE_CFG.update(DEFAULT_CFG["trade"])
    API_CFG.update(DEFAULT_CFG["api"])
    st.sidebar.success("Config reset to default values ✅")

# Save button
if st.sidebar.button("💾 Save Config"):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(CFG, f)
    st.sidebar.success("Config saved to file ✅")


# ==============================================================
# 📦 Variables & State
# ==============================================================
trade_log   = []
log_messages = []

usdt_balance = broker.fetch_balance().get("USDT", {}).get("free", 0.0)
open_trades  = []

# === Restore Open Trades from DB ===
cur.execute("""
WITH paired AS (
    SELECT t1.id AS buy_id, MIN(t2.id) AS sell_id
    FROM trades t1
    LEFT JOIN trades t2
      ON t2.signal='SELL' AND t2.id > t1.id
    WHERE t1.signal='BUY'
    GROUP BY t1.id
)
SELECT price FROM trades
WHERE id IN (SELECT buy_id FROM paired WHERE sell_id IS NULL)
""")
rows = cur.fetchall()
open_trades = [r[0] for r in rows]

# === Current Open BUY Count ===
cur.execute("""
WITH paired AS (
    SELECT t1.id AS buy_id, MIN(t2.id) AS sell_id
    FROM trades t1
    LEFT JOIN trades t2
      ON t2.signal='SELL' AND t2.id > t1.id
    WHERE t1.signal='BUY'
    GROUP BY t1.id
)
SELECT COUNT(*) FROM trades
WHERE id IN (SELECT buy_id FROM paired WHERE sell_id IS NULL)
""")
current_open_buys = cur.fetchone()[0] or 0

# Config limits
max_open_trades = RISK_CFG["max_open_trades"]

# Total buys (all-time)
cur.execute("SELECT COUNT(*) FROM trades WHERE signal='BUY'")
total_buys = cur.fetchone()[0] or 0


# ==============================================================
# 🧭 Sidebar Layout (Status)
# ==============================================================
st.sidebar.header("⚙️ Bot Status")

restored_box        = st.sidebar.empty()
sidebar_rsi         = st.sidebar.empty()
buy_level_box       = st.sidebar.empty()
sell_level_box      = st.sidebar.empty()
total_buys_box      = st.sidebar.empty()
sidebar_open_trades = st.sidebar.empty()

# Account Balances
try:
    balances = broker.fetch_balance()
    if balances:
        df_bal = pd.DataFrame([
            {"asset": k,
             "free": v.get("free", 0.0),
             "used": v.get("used", 0.0),
             "total": v.get("total", 0.0)}
            for k, v in balances.items()
            if isinstance(v, dict) and float(v.get("total", 0.0)) > 0
        ])
        st.sidebar.subheader("💰 Account Balances")
        st.sidebar.dataframe(df_bal, height=250)
except Exception as e:
    st.sidebar.error(f"Balance fetch error: {e}")

# Error / Trade Log
st.sidebar.subheader("📜 Trade / Error Log")
log_box = st.sidebar.empty()


# ==============================================================
# 🔝 Top Metrics (3 columns)
# ==============================================================
col1, col2, col3 = st.columns([1, 1, 1], gap="large")

with col1:
    metric_price = st.metric("📈 Live Price", "...")
with col2:
    metric_signal = st.metric("📊 Signal", "HOLD")
with col3:
    metric_balance = st.metric("💰 Balance", f"{usdt_balance:.2f} USDT")


# ==============================================================
# 📑 Trade History + Charts
# ==============================================================
st.markdown("### 📑 Trade History")
history_table = st.empty()

st.markdown("### 📈 Performance Charts")
rsi_chart    = st.empty()
equity_chart = st.empty()


# ==============================================================
# 🔄 Main Live Loop
# ==============================================================
while True:
    try:
        # --- Live Price ---
        ticker = broker.fetch_ticker(API_CFG["symbol"])
        price  = ticker["last"]
        metric_price.metric("📈 Live Price", f"{price:.2f} USDT")

        # --- OHLCV & Indicators ---
        lookback = STRAT["lookback"]
        ohlcv = fetch_ohlcv(API_CFG["symbol"], timeframe="1m", limit=lookback)

        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms")

        signals, indicators = rsi_ma_signals(
            df,
            STRAT["rsi_len"], STRAT["ma_len"], STRAT["atr_len"],
            STRAT["use_atr_filter"], STRAT["atr_thresh"],
            STRAT["rsi_buy_below"], STRAT["rsi_sell_above"],
        )

        rsi_val    = indicators["rsi"].iloc[-1]
        buy_level  = STRAT["rsi_buy_below"]
        sell_level = STRAT["rsi_sell_above"]
        qty        = TRADE_CFG["quantity"]

        # --- Signal Logic ---
        if rsi_val <= buy_level and len(open_trades) < max_open_trades:
            signal = "BUY"
        elif rsi_val >= sell_level and len(open_trades) > 0:
            signal = "SELL"
        else:
            signal = "HOLD"

        # --- Update Metrics ---
        metric_signal.metric("📊 Signal", signal)
        metric_balance.metric("💰 Balance", f"{usdt_balance:.2f} USDT")

        # --- Sidebar Updates ---
        restored_box.markdown(
            f"<div class='status-box' style='background:#fdf6e3;color:brown;'>📦 Restored {current_open_buys} open BUY trades from DB</div>",
            unsafe_allow_html=True
        )
        sidebar_rsi.markdown(
            f"<div class='status-box' style='background:#e8f0fe;color:#1a73e8;'>📊 Live RSI: {rsi_val:.2f}</div>",
            unsafe_allow_html=True
        )
        buy_level_box.markdown(
            f"<div class='status-box' style='background:#e6f9ec;color:green;'>🟢 Buy Level RSI: {buy_level}</div>",
            unsafe_allow_html=True
        )
        sell_level_box.markdown(
            f"<div class='status-box' style='background:#fdeaea;color:#b22222;'>🔴 Sell Level RSI: {sell_level}</div>",
            unsafe_allow_html=True
        )
        total_buys_box.markdown(
            f"<div class='status-box' style='background:#e6f4ea;color:green;'>✅ Total Buys: {len(open_trades)}/{max_open_trades}</div>",
            unsafe_allow_html=True
        )
        sidebar_open_trades.markdown(
            f"<div class='status-box' style='background:#fff9e6;color:#a0522d;'>🔓 Open Trades: {len(open_trades)}</div>",
            unsafe_allow_html=True
        )

        # ==============================================================
        # 💸 Trade Execution
        # ==============================================================
        trade_note, profit = "", None

        if signal == "BUY":
            est_cost = price * qty
            free_usdt = broker.fetch_balance().get("USDT", {}).get("free", 0.0)

            if est_cost <= free_usdt:
                try:
                    broker.create_order(API_CFG["symbol"], "buy", "market", qty)
                    open_trades.append(price)
                    total_buys += 1
                    trade_note = f"🟢 BUY at {price}, RSI={rsi_val:.2f}, Balance={usdt_balance:.2f}"
                except Exception as api_err:
                    trade_note = f"⚠️ API Error on BUY: {api_err}"
            else:
                trade_note = "⚠️ Insufficient balance for BUY"

        elif signal == "SELL" and open_trades:
            entry_price = open_trades.pop(0)
            try:
                broker.create_order(API_CFG["symbol"], "sell", "market", qty)
                profit = (price - entry_price) * qty
                usdt_balance += profit
                trade_note = f"🔴 SELL at {price}, RSI={rsi_val:.2f}, PnL={profit:.2f}, Balance={usdt_balance:.2f}"
            except Exception as api_err:
                trade_note = f"⚠️ API Error on SELL: {api_err}"

        # --- Logging ---
        if trade_note:
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_messages.append(f"{timestamp} | {trade_note}")
            log_box.text_area("Log", "\n".join(log_messages[-20:]), height=400)

        # ==============================================================
        # 💾 Save Trade Log
        # ==============================================================
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "price": price,
            "signal": signal,
            "rsi": rsi_val,
            "usdt_balance": usdt_balance,
            "pnl": profit,
            "note": trade_note,
        }
        trade_log.append(log_entry)

        # --- Trade History Table ---
        history_df = pd.DataFrame(trade_log)
        if not history_df.empty:
            def highlight_signals(val):
                color = "green" if val == "BUY" else "red" if val == "SELL" else "gray"
                return f"color:{color};font-weight:bold;"

            history_table.dataframe(
                history_df.style.applymap(highlight_signals, subset=["signal"]),
                height=300
            )

        # ==============================================================
        # 📊 Charts
        # ==============================================================
        if not history_df.empty:
            # RSI Chart
            rsi_fig = go.Figure()
            rsi_fig.add_trace(go.Scatter(x=df["time"], y=indicators["rsi"],
                                         mode="lines", line=dict(color="black", width=2), name="RSI"))
            rsi_fig.add_hline(y=buy_level, line_dash="dot", line_color="green",
                              annotation_text=f"Buy Level ({buy_level})", annotation_position="right")
            rsi_fig.add_hline(y=sell_level, line_dash="dot", line_color="red",
                              annotation_text=f"Sell Level ({sell_level})", annotation_position="right")
            rsi_fig.add_trace(go.Scatter(x=[df["time"].iloc[-1]], y=[rsi_val],
                                         mode="markers+text",
                                         marker=dict(color="blue", size=12, symbol="circle"),
                                         text=[f"RSI {rsi_val:.2f}"],
                                         textposition="middle right",
                                         name="Current RSI"))
            # Buy / Sell markers
            buys = history_df[history_df["signal"] == "BUY"]
            sells = history_df[history_df["signal"] == "SELL"]
            rsi_fig.add_trace(go.Scatter(x=buys["time"], y=buys["rsi"],
                                         mode="markers", marker=dict(color="green", size=10, symbol="triangle-up"), name="BUY"))
            rsi_fig.add_trace(go.Scatter(x=sells["time"], y=sells["rsi"],
                                         mode="markers", marker=dict(color="red", size=10, symbol="triangle-down"), name="SELL"))
            rsi_fig.update_layout(title="RSI with Buy/Sell Signals", xaxis_title="Time", yaxis_title="RSI")

            rsi_chart.plotly_chart(rsi_fig, use_container_width=True, key=f"rsi_chart_{len(trade_log)}")

            # Equity Curve
            equity_fig = go.Figure()
            equity_fig.add_trace(go.Scatter(x=history_df["time"], y=history_df["usdt_balance"],
                                            mode="lines+markers", line=dict(color="blue", width=2),
                                            fill="tozeroy", name="Balance"))
            equity_fig.update_layout(title="Equity Curve", xaxis_title="Time", yaxis_title="Balance (USDT)")

            equity_chart.plotly_chart(equity_fig, use_container_width=True, key=f"equity_curve_{len(trade_log)}")

        # ==============================================================
        # 🗄️ Save to Database
        # ==============================================================
        cur.execute("""
            INSERT INTO trades (time, symbol, signal, price, qty, balance, rsi, pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_entry["time"], API_CFG["symbol"], signal, price, qty, usdt_balance, rsi_val, profit))
        conn.commit()

        # Wait before next loop
        time.sleep(5)

    except Exception as e:
        log_messages.append(f"⚠️ Error: {e}")
        log_box.text_area("Log", "\n".join(log_messages[-20:]), height=400)
        time.sleep(1)