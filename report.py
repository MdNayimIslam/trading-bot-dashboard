import sqlite3, pandas as pd

# Connect database
conn = sqlite3.connect("trades.db")
df = pd.read_sql("SELECT * FROM trades", conn)

# শুধু BUY আর SELL রাখি
df = df[df["signal"].isin(["BUY","SELL"])].copy().reset_index(drop=True)

# Cycle pairing
trades = []
entry_price, entry_time, entry_qty = None, None, None

for _, row in df.iterrows():
    if row["signal"] == "BUY" and entry_price is None:
        entry_price = row["price"]
        entry_time = row["time"]
        entry_qty  = row["qty"]
    elif row["signal"] == "SELL" and entry_price is not None:
        exit_price = row["price"]
        exit_time  = row["time"]
        profit = (exit_price - entry_price) * entry_qty

        trades.append({
            "Entry Time": entry_time,
            "Entry Price": entry_price,
            "Exit Time": exit_time,
            "Exit Price": exit_price,
            "Qty": entry_qty,
            "PnL (USDT)": profit
        })
        entry_price, entry_time, entry_qty = None, None, None

# Convert to DataFrame
trade_report = pd.DataFrame(trades)

# Summary
print("=== TRADE-BY-TRADE REPORT ===")
print(trade_report.tail(10))
print("\n=== SUMMARY ===")
print(f"Total Trades: {len(trade_report)}")
print(f"Total Profit/Loss: {trade_report['PnL (USDT)'].sum():.2f} USDT")
print(f"Average PnL per Trade: {trade_report['PnL (USDT)'].mean():.2f} USDT")