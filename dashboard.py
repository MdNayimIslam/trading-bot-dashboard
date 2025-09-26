import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
from pathlib import Path
import yaml
import time
import plotly.graph_objects as go

from src.execution.live_broker import LiveBroker
from src.data.connectors.binance import fetch_ohlcv
from src.strategies.rsi_ma import rsi_ma_signals

# === Load Config ===
CONFIG_PATH = Path("config/config.yaml")
CFG = yaml.safe_load(CONFIG_PATH.read_text())

STRAT = CFG["strategy"]
TRADE_CFG = CFG["trade"]
RISK_CFG = CFG["risk"]
API_CFG = CFG["api"]

# === API Credentials ===
API_KEY = st.secrets["API_KEY"]
API_SECRET = st.secrets["API_SECRET"]
SANDBOX = API_CFG["sandbox"]
SYMBOL = API_CFG["symbol"]

# === Init Broker ===
broker = LiveBroker(
    exchange_id="binance",
    api_key=API_KEY,
    secret=API_SECRET,
    sandbox=SANDBOX,
    recv_window_ms=10000,
)

# === Setup DB ===
conn = sqlite3.connect("trades.db", check_same_thread=False)
cur = conn.cursor()
cur.execute(
    """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    ref_id TEXT,
    time TEXT,
    symbol TEXT,
    signal TEXT,
    price REAL,
    qty REAL,
    filled_qty REAL,
    balance REAL,
    rsi REAL,
    pnl REAL
)
"""
)
conn.commit()

# === Streamlit Layout ===
st.set_page_config(page_title="Auto Trading Bot Dashboard", layout="wide")
st.markdown(
    "<h1 style='text-align:center;'>Auto Trading Dashboard</h1>", unsafe_allow_html=True
)

# === Custom CSS ===
st.markdown(
    """
    <style>
    .status-box {
        margin-top: 12px;
        padding: 10px;
        border-radius: 8px;
        font-weight: bold;
    }
    .stMetric {background:#fff;border-radius:12px;padding:15px;
        box-shadow:0 2px 6px rgba(0,0,0,0.1);}
    .block-container {padding-top: 5rem !important;}
    h1 {margin-top:0rem !important;margin-bottom:1rem !important;}
    </style>
""",
    unsafe_allow_html=True,
)

# === Vars ===
trade_log = []
usdt_bal = broker.fetch_balance().get("USDT", {}).get("free", 0.0)
open_trades = []

# === Restore Open Trades ===
cur.execute(
    """
SELECT order_id, price FROM trades
WHERE signal='BUY'
AND order_id IS NOT NULL
AND order_id NOT IN (
    SELECT ref_id FROM trades WHERE signal='SELL' AND ref_id IS NOT NULL
)
"""
)
rows = cur.fetchall()
open_trades = [{"price": r[1], "order_id": r[0]} for r in rows]

# --- Max open trades ---
max_open_trades = RISK_CFG["max_open_trades"]

# === Sidebar ===
st.sidebar.header("⚙️ Bot Status")
restored_box = st.sidebar.empty()
sidebar_rsi = st.sidebar.empty()
buy_level_box = st.sidebar.empty()
sell_level_box = st.sidebar.empty()
total_buys_box = st.sidebar.empty()
sidebar_open_trades = st.sidebar.empty()

# === Account Balances ===
try:
    acct_bal = broker.fetch_balance()
    if acct_bal:
        df_bal = pd.DataFrame(
            [
                {
                    "asset": k,
                    "free": v.get("free", 0.0),
                    "used": v.get("used", 0.0),
                    "total": v.get("total", 0.0),
                }
                for k, v in acct_bal.items()
                if isinstance(v, dict) and float(v.get("total", 0.0)) > 0
            ]
        )
        st.sidebar.subheader("💰 Account Balances")
        st.sidebar.dataframe(df_bal, height=250)
except Exception as acc_err:
    st.sidebar.error(f"Balance fetch error: {acc_err}")

# === Error Log ===
st.sidebar.subheader("📜 Trade / Error Log")
log_box = st.sidebar.empty()
log_messages = []

# === Top Metrics ===
col1, col2, col3 = st.columns([1, 1, 1], gap="large")
with col1:
    metric_price = st.metric("📈 Live Price", "...")
with col2:
    metric_signal = st.metric("📊 Signal", "HOLD")
with col3:
    metric_balance = st.metric("💰 Balance", f"{usdt_bal:.2f} USDT")

# === Trade History ===
st.markdown("### 📑 Trade History")
history_table = st.empty()

# === Charts ===
st.markdown("### 📈 Performance Charts")
rsi_chart = st.empty()
equity_chart = st.empty()

# === Live Loop ===
while True:
    try:
        # === Price ===
        ticker = broker.fetch_ticker(SYMBOL)
        price = ticker["last"]
        metric_price.metric("📈 Live Price", f"{price:.2f} USDT")

        # === Indicators ===
        lookback = STRAT["lookback"]
        ohlcv = fetch_ohlcv(SYMBOL, timeframe="1m", limit=lookback)
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms")

        sig_series, indicators = rsi_ma_signals(
            df,
            STRAT["rsi_len"],
            STRAT["ma_len"],
            STRAT["atr_len"],
            STRAT["use_atr_filter"],
            STRAT["atr_thresh"],
            STRAT["rsi_buy_below"],
            STRAT["rsi_sell_above"],
        )

        rsi_val = indicators["rsi"].iloc[-1]
        buy_level = STRAT["rsi_buy_below"]
        sell_level = STRAT["rsi_sell_above"]

        # === Signal Rule ===
        if rsi_val <= buy_level and len(open_trades) < max_open_trades:
            signal = "BUY"
        elif rsi_val >= sell_level and len(open_trades) > 0:
            signal = "SELL"
        else:
            signal = "HOLD"

        # === Update Metrics ===
        metric_signal.metric("📊 Signal", signal)
        metric_balance.metric("💰 Balance", f"{usdt_bal:.2f} USDT")

        # === Sidebar Live Updates ===
        restored_box.markdown(
            f"<div class='status-box' style='background:#fdf6e3;color:brown;'>📦 Restored {len(open_trades)} open BUY trades from DB</div>",
            unsafe_allow_html=True,
        )
        sidebar_rsi.markdown(
            f"<div class='status-box' style='background:#e8f0fe;color:#1a73e8;'>📊 Live RSI: {rsi_val:.2f}</div>",
            unsafe_allow_html=True,
        )
        buy_level_box.markdown(
            f"<div class='status-box' style='background:#e6f9ec;color:green;'>🟢 Buy Level RSI: {buy_level}</div>",
            unsafe_allow_html=True,
        )
        sell_level_box.markdown(
            f"<div class='status-box' style='background:#fdeaea;color:#b22222;'>🔴 Sell Level RSI: {sell_level}</div>",
            unsafe_allow_html=True,
        )
        total_buys_box.markdown(
            f"<div class='status-box' style='background:#e6f4ea;color:green;'>✅ Total Buys: {len(open_trades)}/{max_open_trades}</div>",
            unsafe_allow_html=True,
        )
        sidebar_open_trades.markdown(
            f"<div class='status-box' style='background:#fff9e6;color:#a0522d;'>🔓 Open Trades: {len(open_trades)}</div>",
            unsafe_allow_html=True,
        )

        # === Trade Execution ===
        trade_note = ""
        profit = None

        # --- BUY ---
        if signal == "BUY":
            free_usdt = broker.fetch_balance().get("USDT", {}).get("free", 0.0)
            qty = (free_usdt * TRADE_CFG.get("quantity_pct", 1.0)) / price
            est_cost = price * qty

            if est_cost < 10:
                trade_note = "⚠️ Trade below Binance minimum $10. Skipping."
            elif est_cost > free_usdt:
                trade_note = "⚠️ Insufficient balance for BUY"
            else:
                try:
                    order = broker.create_order(SYMBOL, "buy", "market", qty)
                    order_id = order["orderId"]
                    filled_qty = float(order.get("filled", qty))
                    open_trades.append({"price": price, "order_id": order_id, "filled_qty": filled_qty})

                    cur.execute(
                        """
                        INSERT INTO trades (order_id, ref_id, time, symbol, signal, price, qty, filled_qty, balance, rsi, pnl)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            order_id,
                            None,
                            datetime.now().strftime("%H:%M:%S"),
                            SYMBOL,
                            "BUY",
                            price,
                            qty,
                            filled_qty,
                            usdt_bal,
                            rsi_val,
                            None,
                        ),
                    )
                    conn.commit()
                    trade_note = f"🟢 BUY id={order_id} at {price}, RSI={rsi_val:.2f}, Balance={usdt_bal:.2f}"
                except Exception as api_err:
                    trade_note = f"⚠️ API Error on BUY: {api_err}"

        # --- SELL ---
        elif signal == "SELL" and len(open_trades) > 0:
            entry = open_trades.pop(0)
            entry_price = entry["price"]
            entry_order_id = entry["order_id"]

            free_base = broker.fetch_balance().get(SYMBOL.split("/")[0], {}).get("free", 0.0)
            sell_qty = free_base * TRADE_CFG.get("quantity_pct", 1.0)

            if price * sell_qty < 10:
                trade_note = "⚠️ Trade below Binance minimum $10. Skipping."
            elif sell_qty <= 0:
                trade_note = f"⚠️ Not enough {SYMBOL.split('/')[0]} balance to SELL"
            else:
                try:
                    order = broker.create_order(SYMBOL, "sell", "market", sell_qty)
                    order_id = order.get("orderId")
                    profit = (price - entry_price) * sell_qty
                    usdt_bal += profit

                    cur.execute(
                        """
                        INSERT INTO trades (order_id, ref_id, time, symbol, signal, price, qty, filled_qty, balance, rsi, pnl)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            order_id,
                            entry_order_id,
                            datetime.now().strftime("%H:%M:%S"),
                            SYMBOL,
                            "SELL",
                            price,
                            sell_qty,
                            sell_qty,
                            usdt_bal,
                            rsi_val,
                            profit,
                        ),
                    )
                    conn.commit()
                    trade_note = f"🔴 SELL id={order_id} (ref={entry_order_id}) at {price}, PnL={profit:.2f}, Balance={usdt_bal:.2f}"
                except Exception as api_err:
                    trade_note = f"⚠️ API Error on SELL: {api_err}"

        # === Log Display ===
        if trade_note:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_messages.append(f"{timestamp} | {trade_note}")
            log_box.text_area("Log", "\n".join(log_messages[-20:]), height=400)

        # === Save Trade Log ===
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "price": price,
            "signal": signal,
            "rsi": rsi_val,
            "usdt_balance": usdt_bal,
            "pnl": profit,
            "note": trade_note,
        }
        trade_log.append(log_entry)

        # === Trade History Table ===
        history_df = pd.DataFrame(trade_log)
        if not history_df.empty:
            def highlight_signals(val):
                color = "green" if val == "BUY" else "red" if val == "SELL" else "gray"
                return f"color:{color};font-weight:bold;"

            history_table.dataframe(
                history_df.style.applymap(highlight_signals, subset=["signal"]),
                height=300,
            )

        # === Charts ===
        if not history_df.empty:
            rsi_fig = go.Figure()
            rsi_fig.add_trace(
                go.Scatter(
                    x=df["time"],
                    y=indicators["rsi"],
                    mode="lines",
                    line=dict(color="black", width=2),
                    name="RSI",
                )
            )
            rsi_fig.add_hline(y=buy_level, line_dash="dot", line_color="green",
                              annotation_text=f"Buy Level ({buy_level})", annotation_position="right")
            rsi_fig.add_hline(y=sell_level, line_dash="dot", line_color="red",
                              annotation_text=f"Sell Level ({sell_level})", annotation_position="right")
            rsi_fig.add_trace(
                go.Scatter(
                    x=[df["time"].iloc[-1]],
                    y=[rsi_val],
                    mode="markers+text",
                    marker=dict(color="blue", size=12, symbol="circle"),
                    text=[f"RSI {rsi_val:.2f}"],
                    textposition="middle right",
                    name="Current RSI",
                )
            )
            buys = history_df[history_df["signal"] == "BUY"]
            sells = history_df[history_df["signal"] == "SELL"]
            rsi_fig.add_trace(
                go.Scatter(
                    x=buys["time"], y=buys["rsi"],
                    mode="markers", marker=dict(color="green", size=10, symbol="triangle-up"), name="BUY"
                )
            )
            rsi_fig.add_trace(
                go.Scatter(
                    x=sells["time"], y=sells["rsi"],
                    mode="markers", marker=dict(color="red", size=10, symbol="triangle-down"), name="SELL"
                )
            )
            rsi_fig.update_layout(title="RSI with Buy/Sell Signals", xaxis_title="Time", yaxis_title="RSI")
            rsi_chart.plotly_chart(rsi_fig, use_container_width=True, key=f"rsi_chart_{len(trade_log)}")

            equity_fig = go.Figure()
            equity_fig.add_trace(
                go.Scatter(
                    x=history_df["time"], y=history_df["usdt_balance"],
                    mode="lines+markers", line=dict(color="blue", width=2), fill="tozeroy", name="Balance"
                )
            )
            equity_fig.update_layout(title="Equity Curve", xaxis_title="Time", yaxis_title="Balance (USDT)")
            equity_chart.plotly_chart(equity_fig, use_container_width=True, key=f"equity_curve_{len(trade_log)}")

        time.sleep(5)

    except Exception as e:
        log_messages.append(f"⚠️ Error: {str(e)}")
        log_box.text_area("Log", "\n".join(log_messages[-20:]), height=400)
        time.sleep(1)
