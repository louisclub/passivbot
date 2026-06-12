# Feature Spec — 3Commas-Style DCA Orders for passivbot

## Goal

Replace passivbot's martingale grid (position_size × double_down_factor) with a proper
3Commas-style DCA schedule where:

- Order sizes follow a fixed volume multiplier schedule (not relative to position size)
- Order prices are derived from the initial entry price P0 (not rolling avg)
- The full grid is predictable before opening a position
- Maximum supported price drop is calculable from config alone
- Only `max_active_so` limit orders are live at any time
- A single take-profit limit order closes 100% of position

This is implemented as an opt-in mode (`dca_mode: true`). Existing passivbot grid logic
is untouched and remains active when `dca_mode: false`.

---

## New Config Parameters

All live under `bot.long` and `bot.short` in the config JSON.

| Parameter | Type | Description | Suggested default |
|-----------|------|-------------|-------------------|
| `dca_mode` | bool | Enable 3Commas DCA mode | `false` |
| `dca_base_order_qty_pct` | float | Base order size as % of `balance × wallet_exposure_limit` | `0.015` |
| `dca_safety_order_qty_pct` | float | First safety order size, same basis | `0.01` |
| `dca_max_safety_orders` | int | Total number of safety orders | `6` |
| `dca_max_active_so` | int | Max limit orders live simultaneously | `3` |
| `dca_price_deviation_pct` | float | % drop from P0 to trigger SO1 | `0.025` |
| `dca_safety_order_volume_scale` | float | Size multiplier per SO (SO2 = SO1 × scale) | `1.5` |
| `dca_safety_order_step_scale` | float | Price step multiplier per SO | `1.2` |
| `dca_take_profit_pct` | float | TP % above average entry price | `0.015` |
| `dca_market_so` | bool | Use market orders for SOs instead of limit | `false` |

### Parameters that are REPLACED (kept in config for non-DCA mode)

When `dca_mode: true`, these existing params are ignored:
- `entry_grid_double_down_factor`
- `entry_grid_spacing_pct`
- `entry_grid_spacing_we_weight`
- `entry_grid_spacing_log_weight`
- `entry_trailing_*`
- `close_grid_markup_start/end`
- `close_grid_qty_pct`
- `close_trailing_*`

These remain active (used in DCA mode):
- `entry_initial_ema_dist` — still controls when initial entry fires
- `wallet_exposure_limit` — still caps total exposure
- `n_positions` — still controls max concurrent positions
- `unstuck_*` — still used for stuck position management

---

## Full Math Derivation

### Setup

```
balance     = current account balance
wel         = wallet_exposure_limit (e.g. 1.0)
base_cost   = balance × wel × dca_base_order_qty_pct
safety_cost = balance × wel × dca_safety_order_qty_pct
S           = dca_safety_order_volume_scale
T           = dca_safety_order_step_scale
D           = dca_price_deviation_pct
M           = dca_max_safety_orders
```

### Order size schedule

```
Q_base      = cost_to_qty(base_cost, P0)           # base order
Q_SO_i      = cost_to_qty(safety_cost × S^i, P0)   # SO i=0,1,...,M-1
```

Note: qty calculated at P0. If P0 is unknown at scheduling time, use current market price
as approximation; reconstruction corrects for this.

### Price schedule (all from P0)

Cumulative price drop at each SO:
```
d_0 = D
d_i = D × T^i    for i ≥ 1

ratio_0 = (1 - d_0)
ratio_i = ratio_{i-1} × (1 - d_i)    for i ≥ 1

P_SO_i = P0 × ratio_i
```

### Worked example ($10k balance, 1.0 exposure)

```
base_cost   = $150  (1.5%)
safety_cost = $100  (1.0%)
S = 1.5, T = 1.2, D = 2.5%, M = 6, TP = 1.5%
```

Assume P0 = $20.00 (HYPE price):

| Level | Cost | Qty | Price | Drop from P0 | Avg after fill |
|-------|------|-----|-------|-------------|----------------|
| Base  | $150 | 7.5 | $20.00 | 0%         | $20.00 |
| SO1   | $100 | 5.1 | $19.50 | -2.5%      | $19.78 |
| SO2   | $150 | 7.9 | $18.93 | -5.35%     | $19.48 |
| SO3   | $225 | 12.2| $18.24 | -8.80%     | $19.10 |
| SO4   | $337 | 19.0| $17.38 | -13.1%     | $18.60 |
| SO5   | $506 | 30.1| $16.30 | -18.5%     | $17.92 |
| SO6   | $759 | 48.2| $15.00 | -25.0%     | $16.97 |

**Maximum supported drop: 25.0%** (price of SO6 vs P0)
**Total capital at max: $2,227** (22.3% of $10k wallet at 1x exposure)
**TP at max position: $17.22** (1.5% above $16.97 avg)

---

## P0 Reconstruction Algorithm (stateless)

Passivbot recalculates every tick from live position state. It does not store P0.
We reconstruct P0 exactly from `pos_price` and `pos_size`.

### Step 1 — Infer N (number of SOs filled)

Build cumulative qty schedule:
```
C_0 = Q_base
C_n = C_{n-1} + Q_SO_{n-1}    for n = 1..M
```

Find N where `|pos_size - C_N| < tolerance` (tolerance = 0.1 × step_size).

Special case: if `pos_size ≈ 0`, N = 0, return initial entry order.

### Step 2 — Reconstruct P0

```
weighted_ratio = Q_base × 1.0
              + Q_SO_0 × ratio_0
              + Q_SO_1 × ratio_1
              + ...
              + Q_SO_{N-1} × ratio_{N-1}

# pos_price = P0 × weighted_ratio / C_N
P0 = pos_price × C_N / weighted_ratio
```

This is exact when fills occurred at limit prices (which they do for limit SOs).
For market orders with slippage, the reconstruction is approximate but close enough.

### Step 3 — Calculate next SO prices

```
for i in 0..min(max_active_so, M - N):
    P_next_SO_i = P0 × ratio_{N + i}
```

These are the exact prices to place the next limit orders.

### Why this works stateless

Every quantity in the reconstruction (`Q_base`, `Q_SO_i`, `ratio_i`) is deterministic
from config params alone. Given any `(pos_size, pos_price)` pair that resulted from
fills at the scheduled prices, P0 is uniquely recoverable. No external state needed.

---

## max_active_so Behavior

With `max_active_so = 3` and `max_safety_orders = 6`:

- Position just opened (0 SOs filled): SO1, SO2, SO3 placed as limit orders
- SO1 fills: cancel SO2+SO3, place SO2, SO3, SO4 (recalculated from new P0 reconstruction)
- SO2 fills: cancel SO3+SO4, place SO3, SO4, SO5
- ...and so on

The bot always maintains exactly `min(max_active_so, remaining_SOs)` live orders.
On each tick, the Rust engine returns the desired order set; Python reconciles with exchange
(cancels stale, places new). This is identical to how existing passivbot grid orders work.

---

## Take Profit Behavior

Single limit order: `TP_price = pos_price × (1 + dca_take_profit_pct)`

Recalculated every tick. As SOs fill and `pos_price` drops, TP price follows down.
This means:
- If SO1 fills and avg drops from $20.00 to $19.78, TP moves from $20.30 to $20.09
- Existing TP order is cancelled and replaced with new price
- Only one TP order exists at any time (full position close)

---

## market_so Option

When `dca_market_so: true`:
- Safety orders are placed as market orders (executed immediately when price reaches level)
- In practice this means: the bot checks if current price ≤ P_SO_n, and if so, sends
  a market buy for Q_SO_n
- Limit orders not placed for those levels
- Useful when exchange has issues with stacked limit orders

When `dca_market_so: false` (default):
- All SOs are placed as limit orders in advance
- Standard 3Commas behavior

---

## Optimization Bounds (add to config)

```json
"optimize": {
  "bounds": {
    "long_dca_base_order_qty_pct":        [0.005, 0.05],
    "long_dca_safety_order_qty_pct":      [0.005, 0.05],
    "long_dca_max_safety_orders":         [3, 12],
    "long_dca_max_active_so":             [2, 5],
    "long_dca_price_deviation_pct":       [0.01, 0.06],
    "long_dca_safety_order_volume_scale": [1.0, 3.0],
    "long_dca_safety_order_step_scale":   [1.0, 2.0],
    "long_dca_take_profit_pct":           [0.005, 0.05]
  }
}
```

`dca_mode` and `dca_market_so` are not optimized (boolean flags, set manually).

---

## Difference vs True 3Commas

| Aspect | True 3Commas | This implementation |
|--------|-------------|---------------------|
| P0 source | Stored in deal state | Reconstructed from pos_price each tick |
| SO prices | Fixed from deal open | Same (reconstructed P0 gives identical prices) |
| Max drop | Fully predictable | Fully predictable |
| Market order SOs | Supported | Supported via `dca_market_so` |
| Active SO limit | Supported | Supported via `max_active_so` |
| TP type | Single or grid | Single limit order |
| Stateful | Yes | No (stateless reconstruction) |

The only behavioral difference: if balance changes mid-deal, our version recalculates
order sizes from new balance while 3Commas keeps original sizes. This is a minor difference
and arguably safer (auto-scales to actual balance).
