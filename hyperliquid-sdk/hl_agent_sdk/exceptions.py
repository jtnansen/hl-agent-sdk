"""Exceptions for the Hyperliquid Agent SDK."""

from __future__ import annotations


class HyperliquidError(Exception):
    """Base exception for all SDK errors."""


class ConfigError(HyperliquidError):
    """Missing or invalid configuration (credentials, env vars)."""


class OrderError(HyperliquidError):
    """Order placement or management failed."""


class PositionError(HyperliquidError):
    """No position found or position state error."""


class TickerError(HyperliquidError):
    """Unknown or invalid ticker symbol."""
