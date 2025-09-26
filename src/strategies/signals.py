# signals.py

def generate_signals(ticker_data):
    """
    Simple example signal:
    If last price is even → Buy
    If last price is odd → Sell
    """
    price = ticker_data.get("last", 0)

    if int(price) % 2 == 0:
        return "buy"
    else:
        return "sell"