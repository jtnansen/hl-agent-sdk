# TRADING.md — Hyperliquid Perps Tool Reference

The actual python script is stored in workspace/scripts/hyperliquid_trading_functions.py

## Quick Reference

| Function | Description |
|---|---|
| `open_trade` | Market or limit entry with optional SL/TP |
| `set_sl` | Add or move a stop-loss on an existing position |
| `layer_tp` | Add one or more TP orders to an existing position |
| `reduce_position` | Reduce a position by percentage |
| `close_position` | Close one symbol fully or partially |
| `close_all` | Close every open position |
| `modify_leverage` | Change leverage and margin mode |
| `get_status` | All open positions + unrealised PnL |
| `get_balance` | Available USDC equity |
| `get_positions` | Raw position data |
| `get_open_orders` | All resting and trigger orders |
| `cancel_orders` | Cancel pending orders for a symbol |
| `cancel_all_orders` | Cancel every open order |
| `search_tickers` | Fuzzy search available perp tickers |
| `get_price` | Mid-market price for a symbol |
| `get_all_prices` | All mid-market prices |
| `get_funding` | Current funding rate snapshot |
| `get_orderbook` | L2 order book snapshot |

---

## Account Info

### `get_balance()`
Returns available USDC equity.
```
get_balance()
# → { account_value, total_margin_used, withdrawable }
```

### `get_status()`
Returns all open positions with unrealised PnL and margin summary.
```
get_status()
# → { positions: [...], account_value, total_margin_used, withdrawable }
```

### `get_positions()`
Returns raw position data from Hyperliquid (less processed than `get_status`).
```
get_positions()
# → { positions: [...], margin_summary: {...} }
```

---

## Opening Trades

### `open_trade(symbol, side, size, leverage, order_type, limit_price, sl, tp, slippage, is_cross)`

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
open_trade("ETH", "long", 0.5, leverage=10, sl=2800.0, tp=3200.0)

# Limit short, isolated margin
open_trade("BTC", "short", 0.01, leverage=20, order_type="limit", limit_price=72000.0, is_cross=False)
```

### `modify_leverage(symbol, leverage, is_cross)`
Change leverage and/or margin mode for a symbol. Can be called before or after opening a position.

| Param | Type | Default |
|---|---|---|
| `symbol` | str | required |
| `leverage` | int | required |
| `is_cross` | bool | `True` |

```python
modify_leverage("SOL", 5, is_cross=False)
```

---

## Managing Positions

### `set_sl(symbol, price, size)`
Add or move a stop-loss on an existing position. Defaults to full position size.

| Param | Type | Default |
|---|---|---|
| `symbol` | str | required |
| `price` | float | required |
| `size` | float | `None` (full position) |

```python
set_sl("ETH", 2750.0)             # full position SL
set_sl("ETH", 2750.0, size=0.25)  # partial SL
```

### `layer_tp(symbol, levels)`
Add one or more take-profit orders to an existing position. Each level specifies a price and the size to close at that level.

| Param | Type | Notes |
|---|---|---|
| `symbol` | str | required |
| `levels` | list[dict] | `[{"price": float, "size": float}, ...]` |

```python
# Single TP
layer_tp("ETH", [{"price": 3200.0, "size": 0.5}])

# Scaled TPs
layer_tp("ETH", [
    {"price": 3100.0, "size": 0.2},
    {"price": 3300.0, "size": 0.2},
    {"price": 3500.0, "size": 0.1},
])
```

### `reduce_position(symbol, percent, slippage)`
Reduce an existing position by a percentage. Uses market order.

| Param | Type | Default |
|---|---|---|
| `symbol` | str | required |
| `percent` | float | `50.0` |
| `slippage` | float | `0.05` |

```python
reduce_position("BTC", percent=25.0)  # trim 25%
```

### `close_position(symbol, size, slippage)`
Close one position fully or partially. Uses market order.

| Param | Type | Default |
|---|---|---|
| `symbol` | str | required |
| `size` | float | `None` (full close) |
| `slippage` | float | `0.05` |

```python
close_position("ETH")              # full close
close_position("ETH", size=0.25)   # partial close
```

### `close_all(slippage)`
Market-close every open position. Use with caution.

```python
close_all()
close_all(slippage=0.03)
```

---

## Orders

### `get_open_orders()`
Returns all resting limit orders and trigger orders (SL/TP).
```python
get_open_orders()
# → { orders: [...] }
```

### `cancel_orders(symbol)`
Cancel all pending orders for a specific symbol (includes SL/TP triggers).
```python
cancel_orders("ETH")
```

### `cancel_all_orders()`
Cancel every open order across all symbols.
```python
cancel_all_orders()
```

---

## Market Data

### `search_tickers(query)`
Fuzzy search available perp tickers. Use this when unsure of the exact ticker string.
```python
search_tickers("PEPE")   # → { matches: ["PEPE"], total_perps: N }
search_tickers("dog")    # → { matches: ["DOGE", "DOGWIFHAT", ...] }
```

### `get_price(symbol)`
Get current mid-market price for a symbol.
```python
get_price("BTC")  # → { coin: "BTC", mid_price: 67423.5 }
```

### `get_all_prices()`
Returns mid-market prices for every listed perp as a dict.
```python
get_all_prices()  # → { prices: { "BTC": 67423.5, "ETH": 3100.0, ... } }
```

### `get_funding(symbol)`
Returns current funding rate, open interest, mark price, and oracle price.
```python
get_funding("ETH")
# → { funding_rate, open_interest, mark_price, oracle_price, premium }
```

### `get_orderbook(symbol, depth)`
Returns L2 order book snapshot with bids and asks.

| Param | Type | Default |
|---|---|---|
| `symbol` | str | required |
| `depth` | int | `10` |

```python
get_orderbook("BTC", depth=5)
# → { bids: [{price, size}, ...], asks: [{price, size}, ...] }
```

---

## Common Workflows

**Before trading an unfamiliar token:**
1. `search_tickers("query")` — confirm exact ticker
2. `get_price("TICKER")` — get current price
3. `open_trade(...)` — place the trade

**Open a trade with risk management in one call:**
- Pass `sl` and `tp` directly into `open_trade` — no need to call `set_sl` or `layer_tp` separately after entry.

**Add scaled TPs after entry:**
- Use `layer_tp` with multiple levels. Make sure the total size across all levels doesn't exceed your position size.

**Move a stop-loss to break-even:**
1. `get_status()` — find entry price
2. `cancel_orders("TICKER")` — cancel existing SL trigger
3. `set_sl("TICKER", entry_price)` — set new SL at entry

**Partial profit-taking:**
- Use `reduce_position("TICKER", percent=50)` for a quick 50% trim, or
- Use `close_position("TICKER", size=X)` for a specific size.

**Before setting SL or layering TPs:**
- Always confirm a position exists first via `get_status()` or `get_positions()`. Both `set_sl` and `layer_tp` will return an error if no position is open.

**Cancelling before closing:**
- Call `cancel_orders("TICKER")` before `close_position` to avoid SL/TP orders being left as orphaned triggers after the position is closed.
