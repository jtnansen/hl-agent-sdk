"""
Quickstart examples for hl-agent-sdk.

Set env vars before running:
    export HL_SECRET_KEY=0x...
    export HL_ACCOUNT_ADDRESS=0x...
    export HL_TESTNET=1   # use testnet while testing!
"""

from hl_agent_sdk import HyperliquidClient

# ── Instantiate ───────────────────────────────────────────────────────────────
# Reads credentials from env vars (HL_SECRET_KEY, HL_ACCOUNT_ADDRESS, HL_TESTNET)
hl = HyperliquidClient()
print(hl)  # HyperliquidClient(address='0x...', network='testnet')

# ── Read-only — no credentials needed for market data ─────────────────────────
read_only = HyperliquidClient()  # only needs env vars for trading calls

btc_price = read_only.get_price("BTC")
print("BTC price:", btc_price)
# → {"ok": True, "coin": "BTC", "mid_price": 98123.5}

orderbook = read_only.get_orderbook("ETH", depth=5)
print("ETH orderbook:", orderbook)

funding = read_only.get_funding("ETH")
print("ETH funding:", funding)

tickers = read_only.search_tickers("dog")
print("Dog tickers:", tickers["matches"])
# → ["DOGE", "DOGWIFHAT", ...]

# ── Account info ──────────────────────────────────────────────────────────────
balance = hl.get_balance()
print("Balance:", balance)
# → {"ok": True, "account_value": 1234.56, "total_margin_used": 0.0, "withdrawable": 1234.56}

status = hl.get_status()
print("Open positions:", status["positions"])

# ── Open a trade ──────────────────────────────────────────────────────────────
result = hl.open_trade(
    symbol="ETH",
    side="long",
    size=0.1,
    leverage=10,
    sl=2800.0,     # optional: stop-loss
    tp=3200.0,     # optional: take-profit
)
print("Trade result:", result)

# ── Limit order ───────────────────────────────────────────────────────────────
limit_result = hl.open_trade(
    symbol="BTC",
    side="short",
    size=0.001,
    leverage=5,
    order_type="limit",
    limit_price=105_000.0,
    is_cross=False,  # isolated margin
)
print("Limit order:", limit_result)

# ── Manage existing position ──────────────────────────────────────────────────
# Move SL to break-even
current = hl.get_status()
if current["positions"]:
    entry = current["positions"][0]["entry_price"]
    hl.cancel_orders("ETH")          # clear old SL/TP triggers
    hl.set_sl("ETH", entry)          # break-even SL

# Layer take-profits
hl.layer_tp("ETH", [
    {"price": 3100.0, "size": 0.04},
    {"price": 3300.0, "size": 0.03},
    {"price": 3500.0, "size": 0.03},
])

# Trim 25% of a position
hl.reduce_position("ETH", percent=25.0)

# Full close
hl.close_position("ETH")

# Nuclear option — close everything
hl.close_all()

# ── Module-level convenience shim (uses default env-var client) ───────────────
from hl_agent_sdk import get_balance, open_trade, get_price  # noqa: E402

print(get_balance())
print(get_price("SOL"))
