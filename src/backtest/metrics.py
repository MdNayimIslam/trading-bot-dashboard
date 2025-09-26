import numpy as np, pandas as pd
def compute_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().fillna(0.0)
def sharpe(returns: pd.Series, periods_per_year: int = 8760) -> float:
    r = returns.values
    if r.std() == 0: return 0.0
    return (r.mean()*periods_per_year) / (r.std()*np.sqrt(periods_per_year))
def max_drawdown(equity: pd.Series) -> float:
    cummax = equity.cummax()
    dd = (equity - cummax)/cummax
    return float(dd.min())
def cagr(equity: pd.Series, periods_per_year: int = 8760) -> float:
    if len(equity)==0: return 0.0
    total_return = equity.iloc[-1]/equity.iloc[0]
    years = len(equity)/periods_per_year
    if years<=0: return 0.0
    return float(total_return**(1/years)-1)
def summarize(equity: pd.Series) -> dict:
    r = compute_returns(equity)
    return {'final_equity': float(equity.iloc[-1]), 'sharpe': float(sharpe(r)), 'max_dd': float(max_drawdown(equity)), 'cagr': float(cagr(equity))}
