import pandas as pd, numpy as np
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    ad = dn.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    r = 100 - 100/(1+rs)
    return r.fillna(50.0)
