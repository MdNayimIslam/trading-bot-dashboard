
from __future__ import annotations

def normalize_fee_slippage(cfg: dict) -> dict:
    """Return a new dict with canonical keys: fee_pct, slippage_pct.
    Accepts synonyms like: fee_rate, fee, commission; slippage_bp, slippage_bps.
    """
    out = dict(cfg or {})
    # Fee
    if 'fee_pct' not in out:
        for k in ('fee_rate','fee','commission','fees'):
            if k in out:
                out['fee_pct'] = out[k]
                break
    # Slippage
    if 'slippage_pct' not in out:
        if 'slippage_bp' in out:
            out['slippage_pct'] = out['slippage_bp'] / 10000.0
        elif 'slippage_bps' in out:
            out['slippage_pct'] = out['slippage_bps'] / 10000.0
        elif 'slippage' in out:
            out['slippage_pct'] = out['slippage']
    return out
