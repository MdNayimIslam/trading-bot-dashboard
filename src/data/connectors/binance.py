
from typing import Optional, List
from datetime import datetime
try:
    import ccxt
except Exception:
    ccxt = None

def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 1000) -> List[list]:
    if ccxt is None:
        raise RuntimeError("ccxt is not installed. Install from requirements.txt")
    ex = ccxt.binance()
    data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return data
