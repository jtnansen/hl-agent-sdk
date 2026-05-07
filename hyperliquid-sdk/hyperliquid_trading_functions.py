"""
OpenClaw × Hyperliquid  —  MCP Tool Registry
==============================================
Drop-in replacement for the Bitunix trading functions.
Uses the official hyperliquid-python-sdk (pip install hyperliquid-python-sdk).

ENV VARS REQUIRED:
    HL_SECRET_KEY       – Private key (API wallet or main wallet) 0x…
    HL_ACCOUNT_ADDRESS  – Public address of the *main* wallet 0x…
    HL_TESTNET          – Set to "1" to use testnet (optional)

TOOL LIST (what the agent sees):
──────────────────────────────────────────────────────────
  parse_signal        → (unchanged — lives in your LLM layer)
  open_trade          → Market or limit entry with optional SL/TP
  layer_tp            → Add TP orders to an existing position
  set_sl              → Add / move a stop-loss on an existing position
  close_position      → Close one symbol (full or partial)
  close_all           → Nuclear close everything
  reduce_position     → Reduce an existing position by a given %
  get_status          → All open positions + unrealised PnL
  get_balance         → Available USDC equity
  get_positions       → Raw position data
  get_open_orders     → All resting / trigger orders
  modify_leverage     → Change leverage + margin mode
  cancel_orders       → Cancel pending orders for a symbol
  cancel_all_orders   → Cancel every open order
  search_tickers      → Fuzzy search available perp tickers
  get_price           → Mid-market price for a symbol
  get_all_prices      → All mid-market prices
  get_funding         → Current funding rate snapshot
  get_orderbook       → L2 book snapshot for a symbol
──────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import logging
from typing import Any, Optional

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# ───────────────────────── logging ─────────────────────────
log = logging.getLogger("hl_tools")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# ───────────────────────── config ──────────────────────────
_SECRET_KEY: str = os.environ.get("HL_SECRET_KEY", "")
_ACCOUNT_ADDRESS: str = os.environ.get("HL_ACCOUNT_ADDRESS", "")
_USE_TESTNET: bool = os.environ.get("HL_TESTNET", "0") == "1"
_BASE_URL: str = constants.TESTNET_API_URL if _USE_TESTNET else constants.MAINNET_API_URL

# ───────────────────────── singletons ──────────────────────
_wallet = None
_exchange: Optional[Exchange] = None
_info: Optional[Info] = None


def _get_wallet():
    global _wallet
    if _wallet is None:
        if not _SECRET_KEY:
            raise RuntimeError("HL_SECRET_KEY env var not set")
        _wallet = eth_account.Account.from_key(_SECRET_KEY)
    return _wallet


def _get_exchange() -> Exchange:
    global _exchange
    if _exchange is None:
        w = _get_wallet()
        kwargs: dict[str, Any] = {"wallet": w, "base_url": _BASE_URL}
        if _ACCOUNT_ADDRESS:
            kwargs["account_address"] = _ACCOUNT_ADDRESS
        _exchange = Exchange(**kwargs)
    return _exchange


def _get_info() -> Info:
    global _info
    if _info is None:
        _info = Info(_BASE_URL, skip_ws=True)
    return _info


def _address() -> str:
    """Return the effective trading address."""
    return _ACCOUNT_ADDRESS or _get_wallet().address


# ───────────────────── helpers ─────────────────────────────

def _meta_universe() -> list[dict]:
    """Cached universe (perpetuals metadata)."""
    if not hasattr(_meta_universe, "_cache"):
        _meta_universe._cache = _get_info().meta()["universe"]
    return _meta_universe._cache


def _coin_names() -> list[str]:
    return [u["name"] for u in _meta_universe()]


def _sz_decimals(coin: str) -> int:
    for u in _meta_universe():
        if u["name"].upper() == coin.upper():
            return u["szDecimals"]
    raise ValueError(f"Unknown coin: {coin}")


def _round_sz(coin: str, sz: float) -> float:
    dec = _sz_decimals(coin)
    return round(sz, dec)


def _round_px(px: float, tick: float = 0.01) -> float:
    """Round price to nearest tick (5 significant figures default)."""
    return round(px, 6)


def _fmt(resp: Any) -> dict:
    """Normalise SDK response into {ok: bool, data: …}."""
    if isinstance(resp, dict):
        ok = resp.get("status") == "ok"
        return {"ok": ok, "data": resp}
    return {"ok": False, "data": str(resp)}


# ═══════════════════════════════════════════════════════════
#  TOOLS
# ═══════════════════════════════════════════════════════════


# ─────────────── open_trade ───────────────────────────────
def open_trade(
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
    exchange = _get_exchange()
    sz = _round_sz(coin, size)

    # Set leverage first
    try:
        exchange.update_leverage(leverage, coin, is_cross=is_cross)
        log.info(f"Leverage set to {leverage}x ({'cross' if is_cross else 'isolated'}) for {coin}")
    except Exception as e:
        log.warning(f"Leverage update note: {e}")

    # Place entry order
    if order_type.lower() == "market":
        result = exchange.market_open(coin, is_buy, sz, slippage=slippage)
    elif order_type.lower() == "limit":
        if limit_price is None:
            return {"ok": False, "error": "limit_price required for limit orders"}
        ot = {"limit": {"tif": "Gtc"}}
        result = exchange.order(coin, is_buy, sz, _round_px(limit_price), ot)
    else:
        return {"ok": False, "error": f"Unknown order_type: {order_type}"}

    entry_resp = _fmt(result)

    # Attach SL/TP if requested
    sl_resp, tp_resp = None, None
    if sl is not None:
        sl_resp = set_sl(coin, sl, size=sz)
    if tp is not None:
        tp_resp = layer_tp(coin, [{"price": tp, "size": sz}])

    return {
        "ok": entry_resp["ok"],
        "entry": entry_resp,
        "sl": sl_resp,
        "tp": tp_resp,
    }


# ─────────────── layer_tp ────────────────────────────────
def layer_tp(
    symbol: str,
    levels: list[dict],
) -> dict:
    """
    Add one or more take-profit orders to an existing position.

    Args:
        symbol: Ticker, e.g. "ETH"
        levels: List of {"price": float, "size": float}
                Size is how much to close at that TP level.
    """
    coin = symbol.upper()
    exchange = _get_exchange()

    # Determine direction from current position
    pos = _position_for(coin)
    if pos is None:
        return {"ok": False, "error": f"No open position for {coin}"}

    is_long = float(pos["szi"]) > 0
    results = []

    for lvl in levels:
        tp_px = lvl["price"]
        tp_sz = _round_sz(coin, lvl["size"])
        ot = {"trigger": {"triggerPx": _round_px(tp_px), "isMarket": True, "tpsl": "tp"}}
        # TP closes position → opposite side, reduce_only
        resp = exchange.order(coin, not is_long, tp_sz, _round_px(tp_px), ot, reduce_only=True)
        results.append(_fmt(resp))

    return {"ok": all(r["ok"] for r in results), "orders": results}


# ─────────────── set_sl ──────────────────────────────────
def set_sl(
    symbol: str,
    price: float,
    size: Optional[float] = None,
) -> dict:
    """
    Add or update a stop-loss on an existing position.

    Args:
        symbol: Ticker
        price:  SL trigger price
        size:   Size to close (defaults to full position)
    """
    coin = symbol.upper()
    exchange = _get_exchange()

    pos = _position_for(coin)
    if pos is None:
        return {"ok": False, "error": f"No open position for {coin}"}

    is_long = float(pos["szi"]) > 0
    pos_sz = abs(float(pos["szi"]))
    sl_sz = _round_sz(coin, size if size else pos_sz)

    ot = {"trigger": {"triggerPx": _round_px(price), "isMarket": True, "tpsl": "sl"}}
    resp = exchange.order(coin, not is_long, sl_sz, _round_px(price), ot, reduce_only=True)
    return _fmt(resp)


# ─────────────── close_position ──────────────────────────
def close_position(
    symbol: str,
    size: Optional[float] = None,
    slippage: float = 0.05,
) -> dict:
    """
    Close a position for one symbol (full or partial).

    Args:
        symbol:   Ticker
        size:     Amount to close (None = entire position)
        slippage: Slippage tolerance
    """
    coin = symbol.upper()
    exchange = _get_exchange()

    if size is not None:
        sz = _round_sz(coin, size)
        resp = exchange.market_close(coin, sz=sz, slippage=slippage)
    else:
        resp = exchange.market_close(coin, slippage=slippage)

    return _fmt(resp)


# ─────────────── close_all ───────────────────────────────
def close_all(slippage: float = 0.05) -> dict:
    """Nuclear option — close every open position."""
    positions = _open_positions()
    results = []
    for pos in positions:
        coin = pos["coin"]
        try:
            resp = close_position(coin, slippage=slippage)
            results.append({"coin": coin, **resp})
        except Exception as e:
            results.append({"coin": coin, "ok": False, "error": str(e)})
    return {"ok": all(r.get("ok") for r in results), "closed": results}


# ─────────────── reduce_position ─────────────────────────
def reduce_position(
    symbol: str,
    percent: float = 50.0,
    slippage: float = 0.05,
) -> dict:
    """
    Reduce an existing position by a percentage.

    Args:
        symbol:  Ticker
        percent: Percentage to reduce (1-100)
        slippage: Slippage tolerance
    """
    coin = symbol.upper()
    pos = _position_for(coin)
    if pos is None:
        return {"ok": False, "error": f"No open position for {coin}"}

    pos_sz = abs(float(pos["szi"]))
    reduce_sz = _round_sz(coin, pos_sz * (percent / 100.0))

    if reduce_sz <= 0:
        return {"ok": False, "error": "Reduction size rounds to zero"}

    return close_position(coin, size=reduce_sz, slippage=slippage)


# ─────────────── get_status ──────────────────────────────
def get_status() -> dict:
    """Return all open positions with unrealised PnL."""
    state = _get_info().user_state(_address())
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


# ─────────────── get_balance ─────────────────────────────
def get_balance() -> dict:
    """Check available USDC equity."""
    state = _get_info().user_state(_address())
    margin = state.get("marginSummary", {})
    return {
        "ok": True,
        "account_value": float(margin.get("accountValue", 0)),
        "total_margin_used": float(margin.get("totalMarginUsed", 0)),
        "withdrawable": float(margin.get("totalRawUsd", 0)),
    }


# ─────────────── get_positions ───────────────────────────
def get_positions() -> dict:
    """Get raw open positions from Hyperliquid."""
    state = _get_info().user_state(_address())
    return {
        "ok": True,
        "positions": state.get("assetPositions", []),
        "margin_summary": state.get("marginSummary", {}),
    }


# ─────────────── get_open_orders ─────────────────────────
def get_open_orders() -> dict:
    """Get all resting and trigger orders."""
    orders = _get_info().open_orders(_address())
    return {"ok": True, "orders": orders}


# ─────────────── modify_leverage ─────────────────────────
def modify_leverage(
    symbol: str,
    leverage: int,
    is_cross: bool = True,
) -> dict:
    """
    Change leverage and margin mode for a symbol.

    Args:
        symbol:   Ticker
        leverage: New leverage multiplier
        is_cross: True for cross margin, False for isolated
    """
    coin = symbol.upper()
    exchange = _get_exchange()
    try:
        resp = exchange.update_leverage(leverage, coin, is_cross=is_cross)
        return _fmt(resp)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────── cancel_orders ───────────────────────────
def cancel_orders(symbol: str) -> dict:
    """Cancel all pending orders for a specific symbol."""
    coin = symbol.upper()
    info = _get_info()
    exchange = _get_exchange()

    orders = info.open_orders(_address())
    to_cancel = [o for o in orders if o["coin"].upper() == coin]

    if not to_cancel:
        return {"ok": True, "cancelled": 0, "message": f"No open orders for {coin}"}

    cancel_reqs = [{"coin": coin, "oid": o["oid"]} for o in to_cancel]
    resp = exchange.bulk_cancel(cancel_reqs)
    return {**_fmt(resp), "cancelled": len(cancel_reqs)}


# ─────────────── cancel_all_orders ───────────────────────
def cancel_all_orders() -> dict:
    """Cancel every open order across all symbols."""
    info = _get_info()
    exchange = _get_exchange()

    orders = info.open_orders(_address())
    if not orders:
        return {"ok": True, "cancelled": 0, "message": "No open orders"}

    cancel_reqs = [{"coin": o["coin"], "oid": o["oid"]} for o in orders]
    resp = exchange.bulk_cancel(cancel_reqs)
    return {**_fmt(resp), "cancelled": len(cancel_reqs)}


# ─────────────── search_tickers ──────────────────────────
def search_tickers(query: str) -> dict:
    """
    Fuzzy search available perpetual tickers on Hyperliquid.

    Args:
        query: Search string, e.g. "ETH", "dog", "pepe"
    """
    q = query.upper()
    matches = [name for name in _coin_names() if q in name.upper()]
    return {"ok": True, "matches": matches, "total_perps": len(_coin_names())}


# ─────────────── get_price ───────────────────────────────
def get_price(symbol: str) -> dict:
    """
    Get current mid-market price for a symbol.

    Args:
        symbol: Ticker, e.g. "ETH", "BTC"
    """
    coin = symbol.upper()
    mids = _get_info().all_mids()
    if coin in mids:
        return {"ok": True, "coin": coin, "mid_price": float(mids[coin])}
    return {"ok": False, "error": f"Ticker {coin} not found"}


# ─────────────── get_all_prices ──────────────────────────
def get_all_prices() -> dict:
    """Get mid-market prices for every listed perp."""
    mids = _get_info().all_mids()
    prices = {k: float(v) for k, v in mids.items()}
    return {"ok": True, "prices": prices}


# ─────────────── get_funding ─────────────────────────────
def get_funding(symbol: str) -> dict:
    """
    Get the current funding rate snapshot for a symbol.

    Args:
        symbol: Ticker
    """
    coin = symbol.upper()
    info = _get_info()
    try:
        # user_state contains funding info; we can also use meta + contexts
        meta = info.meta()
        ctx = info.meta_and_asset_ctxs()
        # ctx is a tuple: (meta_dict, list_of_asset_contexts)
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


# ─────────────── get_orderbook ───────────────────────────
def get_orderbook(symbol: str, depth: int = 10) -> dict:
    """
    Get L2 order book snapshot for a symbol.

    Args:
        symbol: Ticker
        depth:  Number of levels per side (default 10)
    """
    coin = symbol.upper()
    try:
        book = _get_info().l2_snapshot(coin)
        bids = [{"price": float(p["px"]), "size": float(p["sz"])} for p in book["levels"][0][:depth]]
        asks = [{"price": float(p["px"]), "size": float(p["sz"])} for p in book["levels"][1][:depth]]
        return {"ok": True, "coin": coin, "bids": bids, "asks": asks}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ───────────────────── internal helpers ───────────────────

def _open_positions() -> list[dict]:
    """Return list of positions with non-zero size."""
    state = _get_info().user_state(_address())
    out = []
    for p in state.get("assetPositions", []):
        pos = p["position"]
        if float(pos["szi"]) != 0:
            out.append({"coin": pos["coin"], **pos})
    return out


def _position_for(coin: str) -> Optional[dict]:
    """Return position dict for a specific coin, or None."""
    for p in _open_positions():
        if p["coin"].upper() == coin.upper():
            return p
    return None


# ═══════════════════════════════════════════════════════════
#  OPENCLAW TOOL REGISTRY  (import this dict in your agent)
# ═══════════════════════════════════════════════════════════

TOOLS = {
    "open_trade": {
        "fn": open_trade,
        "description": "Place market or limit entry with optional SL/TP on Hyperliquid perps",
        "params": {
            "symbol": "str  — ticker e.g. ETH, BTC, SOL",
            "side": "str  — 'long' or 'short'",
            "size": "float — position size in base asset",
            "leverage": "int  — leverage multiplier (default 10)",
            "order_type": "str  — 'market' or 'limit' (default market)",
            "limit_price": "float | None — required for limit orders",
            "sl": "float | None — stop-loss trigger price",
            "tp": "float | None — take-profit trigger price",
            "slippage": "float — slippage tolerance (default 0.05)",
            "is_cross": "bool — True=cross, False=isolated (default True)",
        },
    },
    "layer_tp": {
        "fn": layer_tp,
        "description": "Add one or more TP orders to an existing position",
        "params": {
            "symbol": "str",
            "levels": "list[dict] — [{price: float, size: float}, ...]",
        },
    },
    "set_sl": {
        "fn": set_sl,
        "description": "Add or move a stop-loss on an existing position",
        "params": {
            "symbol": "str",
            "price": "float — SL trigger price",
            "size": "float | None — partial SL size (default full position)",
        },
    },
    "close_position": {
        "fn": close_position,
        "description": "Close one symbol (full or partial)",
        "params": {
            "symbol": "str",
            "size": "float | None — amount to close (default full)",
            "slippage": "float",
        },
    },
    "close_all": {
        "fn": close_all,
        "description": "Nuclear close everything",
        "params": {"slippage": "float"},
    },
    "reduce_position": {
        "fn": reduce_position,
        "description": "Reduce an existing position by percentage",
        "params": {
            "symbol": "str",
            "percent": "float — 1-100 (default 50)",
            "slippage": "float",
        },
    },
    "get_status": {
        "fn": get_status,
        "description": "All open positions + unrealised PnL",
        "params": {},
    },
    "get_balance": {
        "fn": get_balance,
        "description": "Check available USDC equity",
        "params": {},
    },
    "get_positions": {
        "fn": get_positions,
        "description": "Get raw open positions from Hyperliquid",
        "params": {},
    },
    "get_open_orders": {
        "fn": get_open_orders,
        "description": "List all resting and trigger orders",
        "params": {},
    },
    "modify_leverage": {
        "fn": modify_leverage,
        "description": "Change leverage / margin mode for a symbol",
        "params": {
            "symbol": "str",
            "leverage": "int",
            "is_cross": "bool (default True)",
        },
    },
    "cancel_orders": {
        "fn": cancel_orders,
        "description": "Cancel all pending orders for a symbol",
        "params": {"symbol": "str"},
    },
    "cancel_all_orders": {
        "fn": cancel_all_orders,
        "description": "Cancel every open order across all symbols",
        "params": {},
    },
    "search_tickers": {
        "fn": search_tickers,
        "description": "Fuzzy search available perp tickers on Hyperliquid",
        "params": {"query": "str — search string"},
    },
    "get_price": {
        "fn": get_price,
        "description": "Get mid-market price for a symbol",
        "params": {"symbol": "str"},
    },
    "get_all_prices": {
        "fn": get_all_prices,
        "description": "All mid-market prices",
        "params": {},
    },
    "get_funding": {
        "fn": get_funding,
        "description": "Current funding rate snapshot",
        "params": {"symbol": "str"},
    },
    "get_orderbook": {
        "fn": get_orderbook,
        "description": "L2 order book snapshot",
        "params": {"symbol": "str", "depth": "int (default 10)"},
    },
}


# ═══════════════════════════════════════════════════════════
#  Quick smoke test
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("─── Hyperliquid Tool Registry ───")
    print(f"Network : {'TESTNET' if _USE_TESTNET else 'MAINNET'}")
    print(f"Address : {_address() if _SECRET_KEY else '(not configured)'}")
    print(f"Tools   : {len(TOOLS)}")
    print()
    for name, meta in TOOLS.items():
        print(f"  • {name:20s}  {meta['description']}")

    if _SECRET_KEY:
        print("\n─── Live checks ───")
        print("Balance:", get_balance())
        print("BTC price:", get_price("BTC"))
        print("Ticker search 'PEPE':", search_tickers("PEPE"))
