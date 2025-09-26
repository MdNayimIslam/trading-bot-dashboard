from dataclasses import dataclass
@dataclass
class RiskConfig:
    risk_per_trade: float
    atr_stop_mult: float
    tp_mult: float
    max_open_positions: int
