"""
HyperliquidClient — stateful client wrapping the Hyperliquid Python SDK.

Credentials are read from constructor args first, then environment variables:
    HL_SECRET_KEY       – Private key  0x…
    HL_ACCOUNT_ADDRESS  – Main wallet address  0x…
    HL_TESTNET          – "1" to use testnet
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .exceptions import ConfigError, PositionError, TickerError

log = logging.getLogger(__name__)


class HyperliquidClient:
    """
    Stateful client for Hyperliquid perpetuals trading.

    Args:
        secret_key:      Private key string (0x…).  Falls back to HL_SECRET_KEY env var.
        account_address: Main wallet address.       Falls back to HL_ACCOUNT_ADDRESS env var.
        testnet:         Use testnet endpoint.      Falls back to HL_TESTNET=="1" env var.

    All trading methods return a dict with at minimum:
        {"ok": bool, ...}
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        account_address: Optional[str] = None,
        testnet: Optional[bool] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        import os
        from pathlib import Path

        self._secret_key = secret_key or os.environ.get("HL_SECRET_KEY", "")
        self._account_address = account_address or os.environ.get("HL_ACCOUNT_ADDRESS", "")

        if testnet is None:
            testnet = os.environ.get("HL_TESTNET", "0") == "1"
        self._testnet = testnet
        self._base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL

        # Caching
        if cache_dir is None:
            cache_dir = os.environ.get("HL_CACHE_DIR") or str(Path.home() / ".cache" / "hl_agent_sdk")
        self._cache_path = Path(cache_dir) / ("meta_testnet.json" if testnet else "meta_mainnet.json")

        self._wallet = None
        self._exchange: Optional[Exchange] = None
        self._info: Optional[Info] = None
        self._meta_cache: Optional[list[dict]] = None

    # ──────────────────────────── internals ──────────────────────────────

    def _get_wallet(self):
        if self._wallet is None:
            if not self._secret_key:
                raise ConfigError("secret_key / HL_SECRET_KEY not set")
            self._wallet = eth_account.Account.from_key(self._secret_key)
        return self._wallet

    def _get_exchange(self) -> Exchange:
        if self._exchange is None:
            w = self._get_wallet()
            kwargs: dict[str, Any] = {"wallet": w, "base_url": self._base_url}
            if self._account_address:
                kwargs["account_address"] = self._account_address
            self._exchange = Exchange(**kwargs)
        return self._exchange

    def _get_info(self) -> Info:
        if self._info is None:
            self._info = Info(self._base_url, skip_ws=True)
        return self._info

    def _address(self) -> str:
        return self._account_address or self._get_wallet().address

    def _meta_universe(self, force_refresh: bool = False) -> list[dict]:
        import json
        import time

        if not force_refresh and self._meta_cache:
            return self._meta_cache

        # Try disk cache first
        if not force_refresh and self._cache_path.exists():
            try:
                # Cache for 24 hours
                if (time.time() - self._cache_path.stat().st_mtime) < 86400:
                    with open(self._cache_path, "r") as f:
                        self._meta_cache = json.load(f)
                        return self._meta_cache
            except Exception as e:
                log.warning("Failed to read meta cache: %s", e)

        # Fetch fresh
        log.info("Fetching fresh metadata from Hyperliquid...")
        self._meta_cache = self._get_info().meta()["universe"]

        # Write to disk
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(self._meta_cache, f)
        except Exception as e:
            log.warning("Failed to write meta cache: %s", e)

        return self._meta_cache

    def _coin_names(self) -> list[str]:
        return [u["name"] for u in self._meta_universe()]

    def _sz_decimals(self, coin: str) -> int:
        for u in self._meta_universe():
            if u["name"].upper() == coin.upper():
                return u["szDecimals"]
        raise TickerError(f"Unknown coin: {coin}")

    def _round_sz(self, coin: str, sz: float) -> float:
        return round(sz, self._sz_decimals(coin))

    @staticmethod
    def _round_px(px: float) -> float:
        return round(px, 6)

    @staticmethod
    def _fmt(resp: Any) -> dict:
        if isinstance(resp, dict):
            return {"ok": resp.get("status") == "ok", "data": resp}
        return {"ok": False, "data": str(resp)}

    def _open_positions(self) -> list[dict]:
        state = self._get_info().user_state(self._address())
        out = []
        for p in state.get("assetPositions", []):
            pos = p["position"]
            if float(pos["szi"]) != 0:
                out.append({"coin": pos["coin"], **pos})
        return out

    def _position_for(self, coin: str) -> Optional[dict]:
        for p in self._open_positions():
            if p["coin"].upper() == coin.upper():
                return p
        return None

    # ──────────────────────────── trading ────────────────────────────────

    def open_trade(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int = 10,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        slippage: float = 0.05,
        is_cross: bool = True,
    ) -> dict:
        """
        Place a market or limit entry with optional SL & TP.

        Args:
            symbol:      Ticker, e.g. "ETH", "BTC", "SOL"
            side:        "long" | "short"
            size:        Position size in the asset's base unit
            leverage:    Leverage multiplier (default 10)
            order_type:  "market" | "limit"
            limit_price: Required if order_type == "limit"
            sl:          Stop-loss trigger price (optional)
            tp:          Take-profit trigger price (optional)
            slippage:    Slippage tolerance for market orders (default 5%)
            is_cross:    True for cross margin, False for isolated
        """
        coin = symbol.upper()
        is_buy = side.lower() in ("long", "buy")
        exchange = self._get_exchange()
        sz = self._round_sz(coin, size)

        try:
            exchange.update_leverage(leverage, coin, is_cross=is_cross)
            log.info("Leverage set to %dx (%s) for %s", leverage, "cross" if is_cross else "isolated", coin)
        except Exception as e:
            log.warning("Leverage update note: %s", e)

        if order_type.lower() == "market":
            result = exchange.market_open(coin, is_buy, sz, slippage=slippage)
        elif order_type.lower() == "limit":
            if limit_price is None:
                return {"ok": False, "error": "limit_price required for limit orders"}
            ot = {"limit": {"tif": "Gtc"}}
            result = exchange.order(coin, is_buy, sz, self._round_px(limit_price), ot)
        else:
            return {"ok": False, "error": f"Unknown order_type: {order_type}"}

        entry_resp = self._fmt(result)

        sl_resp = self.set_sl(coin, sl, size=sz) if sl is not None else None
        tp_resp = self.layer_tp(coin, [{"price": tp, "size": sz}]) if tp is not None else None

        return {"ok": entry_resp["ok"], "entry": entry_resp, "sl": sl_resp, "tp": tp_resp}

    def layer_tp(self, symbol: str, levels: list[dict]) -> dict:
        """
        Add one or more take-profit orders to an existing position.

        Args:
            symbol: Ticker
            levels: List of {"price": float, "size": float}
        """
        coin = symbol.upper()
        exchange = self._get_exchange()

        pos = self._position_for(coin)
        if pos is None:
            return {"ok": False, "error": f"No open position for {coin}"}

        is_long = float(pos["szi"]) > 0
        results = []
        for lvl in levels:
            tp_px = lvl["price"]
            tp_sz = self._round_sz(coin, lvl["size"])
            ot = {"trigger": {"triggerPx": self._round_px(tp_px), "isMarket": True, "tpsl": "tp"}}
            resp = exchange.order(coin, not is_long, tp_sz, self._round_px(tp_px), ot, reduce_only=True)
            results.append(self._fmt(resp))

        return {"ok": all(r["ok"] for r in results), "orders": results}

    def set_sl(self, symbol: str, price: float, size: Optional[float] = None) -> dict:
        """
        Add or update a stop-loss on an existing position.

        Args:
            symbol: Ticker
            price:  SL trigger price
            size:   Size to close (defaults to full position)
        """
        coin = symbol.upper()
        exchange = self._get_exchange()

        pos = self._position_for(coin)
        if pos is None:
            return {"ok": False, "error": f"No open position for {coin}"}

        is_long = float(pos["szi"]) > 0
        pos_sz = abs(float(pos["szi"]))
        sl_sz = self._round_sz(coin, size if size else pos_sz)

        ot = {"trigger": {"triggerPx": self._round_px(price), "isMarket": True, "tpsl": "sl"}}
        resp = exchange.order(coin, not is_long, sl_sz, self._round_px(price), ot, reduce_only=True)
        return self._fmt(resp)

    def close_position(self, symbol: str, size: Optional[float] = None, slippage: float = 0.05) -> dict:
        """
        Close a position for one symbol (full or partial).

        Args:
            symbol:   Ticker
            size:     Amount to close (None = entire position)
            slippage: Slippage tolerance
        """
        coin = symbol.upper()
        exchange = self._get_exchange()

        if size is not None:
            resp = exchange.market_close(coin, sz=self._round_sz(coin, size), slippage=slippage)
        else:
            resp = exchange.market_close(coin, slippage=slippage)
        return self._fmt(resp)

    def close_all(self, slippage: float = 0.05) -> dict:
        """Market-close every open position."""
        results = []
        for pos in self._open_positions():
            coin = pos["coin"]
            try:
                resp = self.close_position(coin, slippage=slippage)
                results.append({"coin": coin, **resp})
            except Exception as e:
                results.append({"coin": coin, "ok": False, "error": str(e)})
        return {"ok": all(r.get("ok") for r in results), "closed": results}

    def reduce_position(self, symbol: str, percent: float = 50.0, slippage: float = 0.05) -> dict:
        """
        Reduce an existing position by a percentage.

        Args:
            symbol:  Ticker
            percent: Percentage to reduce (1-100)
            slippage: Slippage tolerance
        """
        coin = symbol.upper()
        pos = self._position_for(coin)
        if pos is None:
            return {"ok": False, "error": f"No open position for {coin}"}

        pos_sz = abs(float(pos["szi"]))
        reduce_sz = self._round_sz(coin, pos_sz * (percent / 100.0))
        if reduce_sz <= 0:
            return {"ok": False, "error": "Reduction size rounds to zero"}
        return self.close_position(coin, size=reduce_sz, slippage=slippage)

    # ─────────────────────────── account ─────────────────────────────────

    def get_status(self) -> dict:
        """Return all open positions with unrealised PnL."""
        state = self._get_info().user_state(self._address())
        positions = []
        for p in state.get("assetPositions", []):
            pos = p["position"]
            positions.append({
                "coin": pos["coin"],
                "side": "long" if float(pos["szi"]) > 0 else "short",
                "size": abs(float(pos["szi"])),
                "entry_price": float(pos["entryPx"]),
                "mark_price": float(pos.get("markPx", 0)),
                "unrealised_pnl": float(pos["unrealizedPnl"]),
                "leverage": pos.get("leverage", {}),
                "margin_used": float(pos.get("marginUsed", 0)),
                "liquidation_price": pos.get("liquidationPx"),
            })
        margin = state.get("marginSummary", {})
        return {
            "ok": True,
            "positions": positions,
            "account_value": float(margin.get("accountValue", 0)),
            "total_margin_used": float(margin.get("totalMarginUsed", 0)),
            "withdrawable": float(margin.get("totalRawUsd", 0)),
        }

    def get_balance(self) -> dict:
        """Check available USDC equity."""
        state = self._get_info().user_state(self._address())
        margin = state.get("marginSummary", {})
        return {
            "ok": True,
            "account_value": float(margin.get("accountValue", 0)),
            "total_margin_used": float(margin.get("totalMarginUsed", 0)),
            "withdrawable": float(margin.get("totalRawUsd", 0)),
        }

    def get_positions(self) -> dict:
        """Get raw open positions."""
        state = self._get_info().user_state(self._address())
        return {
            "ok": True,
            "positions": state.get("assetPositions", []),
            "margin_summary": state.get("marginSummary", {}),
        }

    def get_open_orders(self) -> dict:
        """Get all resting and trigger orders."""
        return {"ok": True, "orders": self._get_info().open_orders(self._address())}

    # ──────────────────────────── orders ─────────────────────────────────

    def modify_leverage(self, symbol: str, leverage: int, is_cross: bool = True) -> dict:
        """Change leverage and margin mode for a symbol."""
        coin = symbol.upper()
        try:
            resp = self._get_exchange().update_leverage(leverage, coin, is_cross=is_cross)
            return self._fmt(resp)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cancel_orders(self, symbol: str) -> dict:
        """Cancel all pending orders for a specific symbol."""
        coin = symbol.upper()
        orders = self._get_info().open_orders(self._address())
        to_cancel = [o for o in orders if o["coin"].upper() == coin]

        if not to_cancel:
            return {"ok": True, "cancelled": 0, "message": f"No open orders for {coin}"}

        cancel_reqs = [{"coin": coin, "oid": o["oid"]} for o in to_cancel]
        resp = self._get_exchange().bulk_cancel(cancel_reqs)
        return {**self._fmt(resp), "cancelled": len(cancel_reqs)}

    def cancel_all_orders(self) -> dict:
        """Cancel every open order across all symbols."""
        orders = self._get_info().open_orders(self._address())
        if not orders:
            return {"ok": True, "cancelled": 0, "message": "No open orders"}

        cancel_reqs = [{"coin": o["coin"], "oid": o["oid"]} for o in orders]
        resp = self._get_exchange().bulk_cancel(cancel_reqs)
        return {**self._fmt(resp), "cancelled": len(cancel_reqs)}

    # ────────────────────────── market data ──────────────────────────────

    def search_tickers(self, query: str) -> dict:
        """Fuzzy search available perpetual tickers."""
        q = query.upper()
        matches = [name for name in self._coin_names() if q in name.upper()]
        return {"ok": True, "matches": matches, "total_perps": len(self._coin_names())}

    def get_price(self, symbol: str) -> dict:
        """Get current mid-market price for a symbol."""
        coin = symbol.upper()
        mids = self._get_info().all_mids()
        if coin in mids:
            return {"ok": True, "coin": coin, "mid_price": float(mids[coin])}
        return {"ok": False, "error": f"Ticker {coin} not found"}

    def get_all_prices(self) -> dict:
        """Get mid-market prices for every listed perp."""
        mids = self._get_info().all_mids()
        return {"ok": True, "prices": {k: float(v) for k, v in mids.items()}}

    def get_funding(self, symbol: str) -> dict:
        """Get the current funding rate snapshot for a symbol."""
        coin = symbol.upper()
        try:
            meta = self._get_info().meta()
            ctx = self._get_info().meta_and_asset_ctxs()
            universe = meta["universe"]
            asset_ctxs = ctx[1] if isinstance(ctx, (list, tuple)) else []
            for u, ac in zip(universe, asset_ctxs):
                if u["name"].upper() == coin:
                    return {
                        "ok": True,
                        "coin": coin,
                        "funding_rate": ac.get("funding"),
                        "open_interest": ac.get("openInterest"),
                        "mark_price": ac.get("markPx"),
                        "oracle_price": ac.get("oraclePx"),
                        "premium": ac.get("premium"),
                    }
            return {"ok": False, "error": f"Funding data not found for {coin}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_orderbook(self, symbol: str, depth: int = 10) -> dict:
        """Get L2 order book snapshot for a symbol."""
        coin = symbol.upper()
        try:
            book = self._get_info().l2_snapshot(coin)
            bids = [{"price": float(p["px"]), "size": float(p["sz"])} for p in book["levels"][0][:depth]]
            asks = [{"price": float(p["px"]), "size": float(p["sz"])} for p in book["levels"][1][:depth]]
            return {"ok": True, "coin": coin, "bids": bids, "asks": asks}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ────────────────────────── info ──────────────────────────────────────

    @property
    def network(self) -> str:
        return "testnet" if self._testnet else "mainnet"

    def __repr__(self) -> str:
        addr = self._account_address or "(no address)"
        return f"HyperliquidClient(address={addr!r}, network={self.network!r})"
