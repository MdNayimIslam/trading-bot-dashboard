import pandas as pd
def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h,l,c = df['high'], df['low'], df['close']
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()
