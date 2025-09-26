#!/usr/bin/env python3
# backtest.py — simple runner that calls src.backtest.cpu_entry.run_once
from typing import Optional, List
import argparse, yaml, numpy as np, pandas as pd, math
from pathlib import Path

# ---------- metrics ----------
def to_np_equity(eq_like):
    try:
        return np.asarray(eq_like, dtype=float).reshape(-1)
    except Exception:
        try:
            return np.asarray(getattr(eq_like, "values", eq_like), dtype=float).reshape(-1)
        except Exception:
            return np.array([], dtype=float)

def calc_metrics(eq: np.ndarray, trades: Optional[List] = None, bars_per_day: int = 24):
    if eq is None or eq.size == 0:
        return {"final": float("nan"), "ret_pct": float("nan"), "dd_pct": float("nan"),
                "sharpe": float("nan"), "win_pct": 0.0, "trades": 0}
    rets = np.diff(eq) / eq[:-1] if eq.size > 1 else np.array([])
    if rets.size:
        daily = pd.Series(rets).groupby(np.arange(rets.size) // bars_per_day).sum()
        std = float(daily.std())
        sharpe = float((daily.mean() / (std if std else 1.0)) * math.sqrt(252)) if daily.size > 1 else 0.0
    else:
        sharpe = 0.0
    peak = np.maximum.accumulate(eq)
    dd = np.min(eq / np.maximum(peak, 1e-12) - 1.0) if eq.size else 0.0
    tr = trades or []
    wins = sum(1 for t in tr if float(getattr(t, "pnl", 0.0)) > 0.0)
    ntr = len(tr)
    win_pct = 100.0 * wins / ntr if ntr else 0.0
    return {
        "final": float(eq[-1]),
        "ret_pct": float((eq[-1] / eq[0] - 1.0) * 100.0),
        "dd_pct": float(-dd * 100.0),
        "sharpe": float(sharpe),
        "win_pct": float(win_pct),
        "trades": ntr,
    }

def print_line(tag, m):
    print(f"{tag:16s} | Final:{m['final']:9.2f} | Return:{m['ret_pct']:6.2f}% | "
          f"DD:{m['dd_pct']:6.2f}% | Sharpe:{m['sharpe']:4.2f} | Win%:{m['win_pct']:5.1f} | "
          f"Trades:{m['trades']:3d}")

def parse_symbols_arg(arg: Optional[str] = None):
    if not arg:
        return []
    parts = []
    for chunk in arg.split(','):
        parts.extend(chunk.split())
    return [x.strip() for x in parts if x.strip()]

# ---------- engine wrappers ----------
def run_once_wrapper(cfg: dict, dataset_path: str, device: str):
    from src.backtest.cpu_entry import run_once  # import here to keep file self-contained
    c = dict(cfg)
    c["dataset"] = dataset_path
    return run_once(c, device=device)

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config/config.yaml', help='YAML config path')
    ap.add_argument('--symbols', default='data/sample_BTCUSDT_1h.csv',
                    help='CSV path(s), comma or space separated')
    ap.add_argument('--device', choices=['cpu', 'gpu'], default='cpu')
    args = ap.parse_args()

    # load cfg
    with open(args.config, 'r') as f:
        cfg = yaml.safe_load(f) or {}
    init_cap = (cfg.get('risk') or {}).get('initial_capital', 10000)

    symbols = parse_symbols_arg(args.symbols)
    if not symbols:
        symbols = ['data/sample_BTCUSDT_1h.csv']

    # run per symbol
    results = []
    eqs = []
    print("=== RESULTS ===")
    for sym in symbols:
        out = run_once_wrapper(cfg, sym, args.device if args.device == 'cpu' else 'cpu')  # keep CPU path stable
        eq = to_np_equity(out.get("equity"))
        m = calc_metrics(eq, out.get("trades"))
        print_line(Path(sym).name, m)
        results.append(out)
        eqs.append(eq)

    # equal-weight portfolio on overlap
    eqs = [e for e in eqs if e is not None and e.size]
    if len(eqs) >= 2:
        L = min(e.size for e in eqs)
        norm = [e[:L] / init_cap for e in eqs]
        port = (np.mean(norm, axis=0) * init_cap).astype(float)
        pm = calc_metrics(port, None)
        print("-" * 98)
        print_line("PORT(50/50 ew)", pm)

    print("Done.")

if __name__ == '__main__':
    main()