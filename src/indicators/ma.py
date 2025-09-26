# ema.py

def ema_indicator(prices, period=10):
    """
    Calculate Exponential Moving Average (EMA)
    prices: List or Pandas Series
    period: Integer, window size
    Returns: List of EMA values
    """
    ema = []
    k = 2 / (period + 1)

    for i, price in enumerate(prices):
        if i == 0:
            ema.append(price)
        else:
            ema.append(price * k + ema[-1] * (1 - k))

    return ema