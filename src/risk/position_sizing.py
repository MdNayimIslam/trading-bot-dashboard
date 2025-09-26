def atr_position_size(balance: float, risk_per_trade: float, atr: float, price: float, stop_mult: float) -> float:
    risk_per_unit = max(1e-8, atr * stop_mult)
    risk_amount = balance * risk_per_trade
    qty = risk_amount / risk_per_unit
    return max(0.0, qty)
