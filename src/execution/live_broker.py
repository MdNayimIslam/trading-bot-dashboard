from __future__ import annotations
from typing import Any, Dict, Optional
import time, os, uuid, logging

try:
    import ccxt
except Exception:
    ccxt = None

log = logging.getLogger("live_broker")
log.setLevel(logging.INFO)

class LiveBroker:
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        password: Optional[str] = None,
        sandbox: bool = True,
        recv_window_ms: int = 5000,
        retries: int = 5,
        backoff: float = 0.5,
        enable_time_sync: bool = True,
        client_id_prefix: str = "bot",
        **kwargs: Any,
    ):
        if ccxt is None:
            raise ImportError("ccxt is not installed. Please `pip install ccxt`.")
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Exchange {exchange_id} not supported by ccxt.")

        # ✅ adjustForTimeDifference
        ex = getattr(ccxt, exchange_id)({
            "apiKey": api_key or os.getenv("API_KEY", ""),
            "secret": secret or os.getenv("API_SECRET", ""),
            "password": password or os.getenv("API_PASSWORD", ""),
            "enableRateLimit": True,
            "options": {
                "adjustForTimeDifference": True,
                "recvWindow": recv_window_ms   # ✅ set recvWindow here
            },
            **kwargs,
        })

        # ✅ Sandbox mode
        if sandbox and hasattr(ex, "set_sandbox_mode"):
            ex.set_sandbox_mode(True)
            ex.urls['api'] = 'https://testnet.binance.vision'

        self.exchange = ex
        self.retries = retries
        self.backoff = backoff
        self.recv_window_ms = recv_window_ms
        self.client_id_prefix = client_id_prefix
        self.enable_time_sync = enable_time_sync
        self._last_server_time = None
        self._time_drift_ms = 0

        # ✅ Load markets safely
        try:
            self.exchange.load_markets()
        except Exception as e:
            if sandbox:
                log.warning("Skipping load_markets in testnet: " + str(e))
            else:
                raise

        # ✅ Sync clock drift & override ccxt clock
        if self.enable_time_sync and hasattr(self.exchange, "fetch_time"):
            try:
                self._sync_time()
                # Force ccxt to use drift-adjusted clock
                self.exchange.milliseconds = self.now_ms
            except Exception as e:
                log.warning(f"Time sync failed: {e}")

    # -------- Utilities --------
    def _sync_time(self):
        t0 = time.time()
        server_ms = int(self.exchange.fetch_time())
        t1 = time.time()
        rtt_ms = (t1 - t0) * 1000.0
        local_ms = ((t0 + t1) / 2.0) * 1000.0
        self._last_server_time = server_ms
        self._time_drift_ms = server_ms - local_ms
        log.info(f"Exchange time drift ≈ {self._time_drift_ms:.1f} ms, RTT ≈ {rtt_ms:.1f} ms")

    def now_ms(self):
        if self._last_server_time is None:
            return int(time.time() * 1000)
        return int(time.time() * 1000 + self._time_drift_ms)

    def _retry(self, fn, *args, **kwargs):
        delay = self.backoff
        last = None
        for i in range(self.retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last = e
                log.warning(f"{fn.__name__} failed (attempt {i+1}/{self.retries}): {e}")
                time.sleep(delay)
                delay *= 2.0
        raise last

    def new_client_order_id(self) -> str:
        return f"{self.client_id_prefix}-{uuid.uuid4().hex[:16]}"

    def _amount_to_precision(self, symbol: str, amount: float) -> float:
        try:
            return float(self.exchange.amount_to_precision(symbol, float(amount)))
        except Exception:
            return float(amount)

    def _price_to_precision(self, symbol: str, price: float) -> float:
        try:
            return float(self.exchange.price_to_precision(symbol, float(price)))
        except Exception:
            return float(price)

    # -------- Public REST ops --------
    def create_order(self, symbol: str, side: str, type_: str, amount: float, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None):
        params = dict(params or {})
        if "clientOrderId" not in params:
            params["clientOrderId"] = self.new_client_order_id()

        amt = self._amount_to_precision(symbol, amount)
        px = None
        if price is not None and type_.lower() != "market":
            px = self._price_to_precision(symbol, price)

        # 🚀 Place order via ccxt
        order = self._retry(self.exchange.create_order, symbol, type_, side, amt, px, params)

        # ✅ Normalize order id
        order_id = order.get("id") or order.get("orderId") or params["clientOrderId"]
        order["orderId"] = order_id   # সবসময় থাকবে

        return order

    def cancel_order(self, id: str, symbol: str, params: Optional[Dict[str, Any]] = None):
        return self._retry(self.exchange.cancel_order, id, symbol, params or {})

    def fetch_order(self, id: str, symbol: str, params: Optional[Dict[str, Any]] = None):
        return self._retry(self.exchange.fetch_order, id, symbol, params or {})

    def fetch_open_orders(self, symbol: Optional[str] = None):
        return self._retry(self.exchange.fetch_open_orders, symbol)

    def fetch_balance(self):
        try:
            return self._retry(self.exchange.fetch_balance)
        except Exception as e:
            if self.exchange.urls.get('api') == 'https://testnet.binance.vision':
                log.warning("Testnet balance fetch failed, returning dummy balance")
                return {"free": {"USDT": 10000}, "used": {"USDT": 0}, "total": {"USDT": 10000}}
            else:
                raise

    def fetch_ticker(self, symbol: str):
        return self._retry(self.exchange.fetch_ticker, symbol)

    # -------- New Utility: Account Overview --------
    def fetch_account_overview(self, include_futures: bool = True) -> Dict[str, Any]:
        bal = self.fetch_balance()
        spot = {}
        total_equity = 0.0
        ticker_cache: Dict[str, float] = {}

        def get_price_in_usdt(asset: str) -> Optional[float]:
            if asset in ("USDT", "BUSD"):
                return 1.0
            sym = f"{asset}/USDT"
            try:
                t = self.fetch_ticker(sym)
                return float(t.get("last", t.get("close", 0.0)))
            except Exception:
                try:
                    sym2 = f"{asset}/BTC"
                    t2 = self.fetch_ticker(sym2)
                    btc_price = ticker_cache.get("BTC/USDT")
                    if btc_price is None:
                        btc_price = float(self.fetch_ticker("BTC/USDT")["last"])
                        ticker_cache["BTC/USDT"] = btc_price
                    return float(t2.get("last", 0.0)) * btc_price
                except Exception:
                    return None

        free = bal.get("free", {})
        used = bal.get("used", {})
        total = bal.get("total", {})

        for asset, tot in total.items():
            fr = float(free.get(asset, 0.0) or 0.0)
            us = float(used.get(asset, 0.0) or 0.0)
            t = float(tot or 0.0)
            if t == 0:
                continue
            price = ticker_cache.get(f"{asset}/USDT")
            if price is None:
                price = get_price_in_usdt(asset)
                if price is not None:
                    ticker_cache[f"{asset}/USDT"] = price
            usdt_value = t * (price if price else 0.0)
            spot[asset] = {"free": fr, "used": us, "total": t, "usdt_value": usdt_value}
            total_equity += usdt_value

        futures_info = None
        if include_futures:
            try:
                futures_info = self._retry(self.exchange.fetch_balance, {"type": "future"})
            except Exception:
                futures_info = None

        try:
            server_time = int(self.exchange.fetch_time())
        except Exception:
            server_time = int(time.time() * 1000)

        try:
            import pandas as _pd
            rows = [{"asset": a, **info} for a, info in spot.items()]
            spot_df = _pd.DataFrame(rows).sort_values("usdt_value", ascending=False)
        except Exception:
            spot_df = None

        return {
            "spot": spot,
            "spot_df": spot_df,
            "total_spot_equity": total_equity,
            "futures": futures_info,
            "server_time": server_time,
        }
