import pandas as pd

def load_ohlcv(path, default_path=None):
    """
    Load OHLCV data from a CSV file.
    Auto-detects common column names and maps them to:
    ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    """
    df = pd.read_csv(path)
    
    # Standardize column names
    cols = [c.lower() for c in df.columns]
    rename_map = {}

    if "time" in cols:
        rename_map[df.columns[cols.index("time")]] = "timestamp"
    elif "date" in cols:
        rename_map[df.columns[cols.index("date")]] = "timestamp"

    if "open" in cols:
        rename_map[df.columns[cols.index("open")]] = "open"
    if "high" in cols:
        rename_map[df.columns[cols.index("high")]] = "high"
    if "low" in cols:
        rename_map[df.columns[cols.index("low")]] = "low"
    if "close" in cols:
        rename_map[df.columns[cols.index("close")]] = "close"
    if "volume" in cols:
        rename_map[df.columns[cols.index("volume")]] = "volume"

    df = df.rename(columns=rename_map)

    required = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col} in {path}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df[required]
