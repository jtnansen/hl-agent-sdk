# hl-agent-sdk

Hyperliquid perpetuals trading SDK designed for AI agents. Wraps the official
[hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) with a clean,
stateful `HyperliquidClient` class plus module-level convenience functions for drop-in use.

## Install

```bash
pip install hl-agent-sdk
```

Or install from source (editable):

```bash
git clone <repo>
cd hyperliquid-sdk
pip install -e .
```

## Credentials

Set environment variables before use:

```bash
export HL_SECRET_KEY=0x...           # API wallet or main wallet private key
export HL_ACCOUNT_ADDRESS=0x...      # Main wallet public address
export HL_TESTNET=1                  # Optional — omit or set to 0 for mainnet
```

Or pass credentials directly to the constructor:

```python
from hl_agent_sdk import HyperliquidClient

hl = HyperliquidClient(
    secret_key="0x...",
    account_address="0x...",
    testnet=True,
)
```

## Quick Start

```python
from hl_agent_sdk import HyperliquidClient

hl = HyperliquidClient()  # reads from env vars

# Check balance
print(hl.get_balance())
# → {"ok": True, "account_value": 1500.0, "total_margin_used": 200.0, "withdrawable": 1300.0}

# Open a 10x ETH long with SL and TP
hl.open_trade("ETH", "long", size=0.1, leverage=10, sl=2800.0, tp=3200.0)

# Close it
hl.close_position("ETH")
```

### Module-level shorthand

If you just want drop-in functions without managing a client instance:

```python
from hl_agent_sdk import open_trade, get_balance, get_price

get_balance()
get_price("BTC")
open_trade("SOL", "long", 1.0, leverage=5)
```

These all share a single default `HyperliquidClient` created from env vars on first use.

---

## API Reference

All methods return a dict with at minimum `{"ok": bool, ...}`.

### Account

| Method | Description |
|---|---|
| `get_balance()` | Available USDC equity |
| `get_status()` | All open positions with unrealised PnL |
| `get_positions()` | Raw position data from Hyperliquid |
| `get_open_orders()` | All resting and trigger orders |

```python
hl.get_status()
# → {
#     "ok": True,
#     "positions": [{"coin": "ETH", "side": "long", "size": 0.1, "entry_price": 3000.0, ...}],
#     "account_value": 1500.0,
#     "total_margin_used": 150.0,
#     "withdrawable": 1350.0,
# }
```

### Opening Trades

#### `open_trade(symbol, side, size, leverage, order_type, limit_price, sl, tp, slippage, is_cross)`

| Param | Type | Default | Notes |
|---|---|---|---|
| `symbol` | str | required | e.g. `"ETH"`, `"BTC"`, `"SOL"` |
| `side` | str | required | `"long"` or `"short"` |
| `size` | float | required | Position size in base asset units |
| `leverage` | int | `10` | Leverage multiplier |
| `order_type` | str | `"market"` | `"market"` or `"limit"` |
| `limit_price` | float | `None` | Required if `order_type="limit"` |
| `sl` | float | `None` | Stop-loss trigger price |
| `tp` | float | `None` | Single take-profit trigger price |
| `slippage` | float | `0.05` | Slippage tolerance (5%) |
| `is_cross` | bool | `True` | `True`=cross margin, `False`=isolated |

```python
# Market long with SL and TP
hl.open_trade("ETH", "long", 0.1, leverage=10, sl=2800.0, tp=3200.0)

# Limit short, isolated margin
hl.open_trade("BTC", "short", 0.001, leverage=20, order_type="limit",
              limit_price=105_000.0, is_cross=False)
```

#### `modify_leverage(symbol, leverage, is_cross)`

Change leverage and/or margin mode. Can be called before or after opening.

```python
hl.modify_leverage("SOL", 5, is_cross=False)
```

### Managing Positions

#### `set_sl(symbol, price, size=None)`

Add or move a stop-loss. Defaults to the full position size.

```python
hl.set_sl("ETH", 2750.0)             # full position
hl.set_sl("ETH", 2750.0, size=0.05)  # partial
```

#### `layer_tp(symbol, levels)`

Add one or more take-profit levels. Each level specifies a price and size to close.

```python
hl.layer_tp("ETH", [
    {"price": 3100.0, "size": 0.04},
    {"price": 3300.0, "size": 0.03},
    {"price": 3500.0, "size": 0.03},
])
```

#### `reduce_position(symbol, percent=50.0, slippage=0.05)`

Trim a position by percentage via market order.

```python
hl.reduce_position("BTC", percent=25.0)
```

#### `close_position(symbol, size=None, slippage=0.05)`

Full or partial market close.

```python
hl.close_position("ETH")              # full
hl.close_position("ETH", size=0.05)   # partial
```

#### `close_all(slippage=0.05)`

Market-close every open position.

```python
hl.close_all()
```

### Orders

| Method | Description |
|---|---|
| `cancel_orders(symbol)` | Cancel all pending orders for a symbol |
| `cancel_all_orders()` | Cancel every open order |

```python
hl.cancel_orders("ETH")   # clears SL/TP triggers for ETH
hl.cancel_all_orders()
```

### Market Data

| Method | Description |
|---|---|
| `search_tickers(query)` | Fuzzy search available perp tickers |
| `get_price(symbol)` | Mid-market price |
| `get_all_prices()` | All mid-market prices |
| `get_funding(symbol)` | Funding rate, OI, mark price, oracle price |
| `get_orderbook(symbol, depth=10)` | L2 book snapshot |

```python
hl.search_tickers("dog")   # → {"matches": ["DOGE", "DOGWIFHAT", ...]}
hl.get_price("BTC")        # → {"ok": True, "coin": "BTC", "mid_price": 98123.5}
hl.get_funding("ETH")      # → {"funding_rate": 0.0001, "open_interest": ..., ...}
hl.get_orderbook("BTC", depth=5)
```

---

## Common Workflows

**Check ticker before trading:**
```python
hl.search_tickers("pepe")  # confirm exact ticker string
hl.get_price("PEPE")
```

**Break-even stop after entry:**
```python
status = hl.get_status()
entry = status["positions"][0]["entry_price"]
hl.cancel_orders("ETH")       # remove existing SL trigger
hl.set_sl("ETH", entry)       # set SL at entry price
```

**Flip direction:**
```python
hl.cancel_orders("ETH")
hl.close_position("ETH")
hl.open_trade("ETH", "short", 0.1, leverage=10)
```

---

## Errors

The SDK raises exceptions from `hl_agent_sdk.exceptions` for unrecoverable errors:

| Exception | Raised when |
|---|---|
| `ConfigError` | `HL_SECRET_KEY` not set when a trading call is made |
| `TickerError` | Unknown coin passed to size-rounding helpers |
| `HyperliquidError` | Base class for all SDK errors |

Network and order errors are returned as `{"ok": False, "error": "..."}` dicts, not exceptions,
so agents can handle them without try/except.

---

## Gotchas

- Minimum order size: **$10 notional**
- Always `cancel_orders` before `close_position` — otherwise SL/TP triggers become orphans
- For isolated margin, set `is_cross=False` on `open_trade` or `modify_leverage`
- `set_sl` and `layer_tp` require an open position; check `get_status()` first if unsure
- BTC prices on Hyperliquid typically have no decimals — pass whole numbers for SL/TP

## Env Vars

| Variable | Required | Description |
|---|---|---|
| `HL_SECRET_KEY` | Yes (trading) | Private key `0x…` |
| `HL_ACCOUNT_ADDRESS` | No | Main wallet address; defaults to key-derived address |
| `HL_TESTNET` | No | Set to `"1"` to use testnet |
