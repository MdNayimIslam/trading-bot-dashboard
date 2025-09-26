
import numpy as np

def monte_carlo_var_cvar(returns: np.ndarray, horizon: int = 1, sims: int = 5000, alpha: float = 0.95):
    """Simple MC VaR/CVaR.
    returns: array of historical periodic returns (e.g., hourly)
    horizon: number of periods to aggregate
    sims: number of simulation paths
    alpha: confidence level for VaR
    """
    if len(returns) == 0:
        return {'VaR': 0.0, 'CVaR': 0.0}
    r = np.asarray(returns)
    mu, sigma = r.mean(), r.std(ddof=1) + 1e-12
    draws = np.random.normal(mu, sigma, size=(sims, horizon))
    agg = draws.sum(axis=1)  # sum of horizon returns
    var = -np.quantile(agg, 1 - alpha)  # loss threshold
    cvar = -agg[agg <= np.quantile(agg, 1 - alpha)].mean()
    if np.isnan(cvar):
        cvar = var
    return {'VaR': float(var), 'CVaR': float(cvar)}
