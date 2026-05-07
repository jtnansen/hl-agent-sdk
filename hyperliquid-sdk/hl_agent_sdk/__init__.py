"""
hl-agent-sdk — Hyperliquid perpetuals trading SDK for AI agents.

Quick start:
    from hl_agent_sdk import HyperliquidClient

    hl = HyperliquidClient()          # reads HL_SECRET_KEY / HL_ACCOUNT_ADDRESS from env
    print(hl.get_balance())
    hl.open_trade("ETH", "long", 0.1, leverage=10)

Alternatively, import the module-level convenience functions which use a
default client instantiated from environment variables:
    from hl_agent_sdk import open_trade, get_balance
    get_balance()
"""

from __future__ import annotations
from typing import Optional

from .client import HyperliquidClient
from .exceptions import HyperliquidError, ConfigError, OrderError, PositionError, TickerError

__version__ = "0.2.0"
__all__ = [
    "HyperliquidClient",
    "HyperliquidError",
    "ConfigError",
    "OrderError",
    "PositionError",
    "TickerError",
    # convenience shims
    "open_trade",
    "layer_tp",
    "set_sl",
    "close_position",
    "close_all",
    "reduce_position",
    "get_status",
    "get_balance",
    "get_positions",
    "get_open_orders",
    "modify_leverage",
    "cancel_orders",
    "cancel_all_orders",
    "search_tickers",
    "get_price",
    "get_all_prices",
    "get_funding",
    "get_orderbook",
]

# ── default client (lazily created from env vars) ──────────────────────────

_default: Optional[HyperliquidClient] = None


def _client() -> HyperliquidClient:
    global _default
    if _default is None:
        _default = HyperliquidClient()
    return _default


# ── convenience shims ──────────────────────────────────────────────────────

def open_trade(symbol, side, size, leverage=10, order_type="market",
               limit_price=None, sl=None, tp=None, slippage=0.05, is_cross=True):
    return _client().open_trade(symbol, side, size, leverage, order_type,
                                limit_price, sl, tp, slippage, is_cross)

def layer_tp(symbol, levels):
    return _client().layer_tp(symbol, levels)

def set_sl(symbol, price, size=None):
    return _client().set_sl(symbol, price, size)

def close_position(symbol, size=None, slippage=0.05):
    return _client().close_position(symbol, size, slippage)

def close_all(slippage=0.05):
    return _client().close_all(slippage)

def reduce_position(symbol, percent=50.0, slippage=0.05):
    return _client().reduce_position(symbol, percent, slippage)

def get_status():
    return _client().get_status()

def get_balance():
    return _client().get_balance()

def get_positions():
    return _client().get_positions()

def get_open_orders():
    return _client().get_open_orders()

def modify_leverage(symbol, leverage, is_cross=True):
    return _client().modify_leverage(symbol, leverage, is_cross)

def cancel_orders(symbol):
    return _client().cancel_orders(symbol)

def cancel_all_orders():
    return _client().cancel_all_orders()

def search_tickers(query):
    return _client().search_tickers(query)

def get_price(symbol):
    return _client().get_price(symbol)

def get_all_prices():
    return _client().get_all_prices()

def get_funding(symbol):
    return _client().get_funding(symbol)

def get_orderbook(symbol, depth=10):
    return _client().get_orderbook(symbol, depth)
