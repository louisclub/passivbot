# Code Map — 3Commas DCA Feature

Implement in this order. Each step is testable before moving to the next.

---

## Step 1 — Add new fields to Rust `BotParams` struct

**File:** `passivbot-rust/src/types.rs`

Find the `BotParams` struct (line ~98). Add these fields alongside the existing ones:

```rust
// 3Commas DCA mode — active when dca_mode: true
pub dca_mode: bool,
pub dca_base_order_qty_pct: f64,       // base order as % of (balance × wallet_exposure_limit)
pub dca_safety_order_qty_pct: f64,     // first safety order as % of same
pub dca_max_safety_orders: usize,      // total number of safety orders (e.g. 6)
pub dca_max_active_so: usize,          // max live limit orders at once (e.g. 3)
pub dca_price_deviation_pct: f64,      // % drop from P0 to trigger SO1 (e.g. 0.025)
pub dca_safety_order_volume_scale: f64,// size multiplier per SO (e.g. 1.5)
pub dca_safety_order_step_scale: f64,  // price step multiplier per SO (e.g. 1.2)
pub dca_take_profit_pct: f64,          // TP % above average entry price (e.g. 0.015)
pub dca_market_so: bool,               // if true, SOs use market orders (not limit)
```

These coexist with existing fields. When `dca_mode = false`, existing grid logic runs unchanged.

---

## Step 2 — Wire new params from Python dict into BotParams

**File:** `passivbot-rust/src/python.rs`

Find where `BotParams` is constructed from the Python dict (search for `entry_grid_double_down_factor`
in this file — it will be in a block parsing the `long` / `short` dicts).

Add parsing for each new field with safe defaults:

```rust
dca_mode: dict.get_item("dca_mode")?.map(|v| v.extract::<bool>()).transpose()?.unwrap_or(false),
dca_base_order_qty_pct: dict.get_item("dca_base_order_qty_pct")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(0.01),
dca_safety_order_qty_pct: dict.get_item("dca_safety_order_qty_pct")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(0.01),
dca_max_safety_orders: dict.get_item("dca_max_safety_orders")?.map(|v| v.extract::<usize>()).transpose()?.unwrap_or(6),
dca_max_active_so: dict.get_item("dca_max_active_so")?.map(|v| v.extract::<usize>()).transpose()?.unwrap_or(3),
dca_price_deviation_pct: dict.get_item("dca_price_deviation_pct")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(0.025),
dca_safety_order_volume_scale: dict.get_item("dca_safety_order_volume_scale")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(1.5),
dca_safety_order_step_scale: dict.get_item("dca_safety_order_step_scale")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(1.2),
dca_take_profit_pct: dict.get_item("dca_take_profit_pct")?.map(|v| v.extract::<f64>()).transpose()?.unwrap_or(0.015),
dca_market_so: dict.get_item("dca_market_so")?.map(|v| v.extract::<bool>()).transpose()?.unwrap_or(false),
```

---

## Step 3 — Implement DCA entry logic in Rust

**File:** `passivbot-rust/src/entries.rs`

Add a new public function. Do NOT modify existing grid functions — call this instead when
`bot_params.dca_mode == true`.

```rust
pub fn calc_dca_entries_long(
    exchange_params: &ExchangeParams,
    bot_params: &BotParams,
    state_params: &StateParams,
    position: &Position,
) -> Vec<Order>
```

### Algorithm inside this function

**Variables:**
```
balance     = state_params.balance
wel         = bot_params.wallet_exposure_limit
base_cost   = balance × wel × bot_params.dca_base_order_qty_pct
safety_cost = balance × wel × bot_params.dca_safety_order_qty_pct
vol_scale   = bot_params.dca_safety_order_volume_scale
step_scale  = bot_params.dca_safety_order_step_scale
dev_pct     = bot_params.dca_price_deviation_pct
max_so      = bot_params.dca_max_safety_orders
max_active  = bot_params.dca_max_active_so
```

**Step 1 — Build the full SO schedule (sizes and price ratios from P0):**
```
base_qty    = cost_to_qty(base_cost, current_price)
so_sizes[i] = cost_to_qty(safety_cost × vol_scale^i, P0)   for i in 0..max_so

price_ratios[0] = 1.0 - dev_pct
price_ratios[i] = price_ratios[i-1] × (1.0 - dev_pct × step_scale^i)
```

Note: P0 is unknown initially — use current_price as placeholder, correct after reconstruction.

**Step 2 — Infer N (filled SOs) from position size:**

If `position.size == 0.0`: no position, N = 0, return initial entry order only.

Otherwise:
```
cumulative_qty[0] = base_qty
cumulative_qty[n] = cumulative_qty[n-1] + so_sizes[n-1]    for n in 1..=max_so

N = argmin_n |position.size - cumulative_qty[n]|
```
Use a tolerance of ±10% of the expected step size. If no match, default to N=0.

**Step 3 — Reconstruct P0 from pos_price and N:**

This is exact if fills occurred at limit prices.

```
// Numerator: weighted sum of prices (as ratios × P0)
weighted_price_sum = base_qty × 1.0            // base order at P0
                   + so_sizes[0] × price_ratios[0]
                   + so_sizes[1] × price_ratios[1]
                   + ...
                   + so_sizes[N-1] × price_ratios[N-1]

// All these are ratios × P0, so:
weighted_price_sum_ratio = base_qty + Σ(so_sizes[i] × price_ratios[i], i=0..N-1)

// pos_price = P0 × weighted_price_sum_ratio / cumulative_qty[N]
P0 = position.price × cumulative_qty[N] / weighted_price_sum_ratio
```

**Step 4 — Calculate next SO prices from P0:**
```
next_so_prices[i] = P0 × price_ratios[N + i]   for i in 0..max_active
                    (capped at max_so - N available SOs)
```

**Step 5 — Build order list:**
```
orders = []
for i in 0..min(max_active, max_so - N):
    qty  = so_sizes[N + i] rounded to exchange qty_step
    price = next_so_prices[i] rounded down to exchange price_step
    if dca_market_so:
        order_type = Market
    else:
        order_type = Limit (LimitBid for long)
    orders.push(Order { qty, price, order_type })
```

Return `orders`. The backtest engine places and tracks these normally.

**For short side:** mirror the logic (prices go up from P0, SOs are asks).

---

## Step 4 — Implement DCA close logic (single TP)

**File:** `passivbot-rust/src/closes.rs`

Add new function:
```rust
pub fn calc_dca_close_long(
    exchange_params: &ExchangeParams,
    bot_params: &BotParams,
    position: &Position,
) -> Vec<Order>
```

Logic:
```
if position.size == 0.0: return []

tp_price = position.price × (1.0 + bot_params.dca_take_profit_pct)
tp_price = round_up(tp_price, exchange_params.price_step)
tp_qty   = round_(position.size.abs(), exchange_params.qty_step)

return [Order { qty: tp_qty, price: tp_price, order_type: LimitAsk }]
```

Single limit order closing 100% of position. Recalculated every tick so it tracks average
entry price as SOs fill and the average moves.

---

## Step 5 — Route DCA mode in backtest and live bot

**File:** `passivbot-rust/src/entries.rs` — in `calc_entries_long` / `calc_next_entry_long`:
```rust
if bot_params.dca_mode {
    return calc_dca_entries_long(exchange_params, bot_params, state_params, position);
}
// existing grid logic below...
```

**File:** `passivbot-rust/src/closes.rs` — in `calc_closes_long` / `calc_next_close_long`:
```rust
if bot_params.dca_mode {
    return calc_dca_close_long(exchange_params, bot_params, position);
}
// existing close logic below...
```

---

## Step 6 — Add new params to Python config

**File:** `configs/HYPE_long.json`

In `bot.long`, add:
```json
"dca_mode": true,
"dca_base_order_qty_pct": 0.015,
"dca_safety_order_qty_pct": 0.01,
"dca_max_safety_orders": 6,
"dca_max_active_so": 3,
"dca_price_deviation_pct": 0.025,
"dca_safety_order_volume_scale": 1.5,
"dca_safety_order_step_scale": 1.2,
"dca_take_profit_pct": 0.015,
"dca_market_so": false
```

Remove or keep (with `dca_mode: false`) the existing grid params — existing params are used
when `dca_mode: false` so they can coexist.

Also update `optimize.bounds` to add new DCA params and exclude old grid params from
optimization bounds when in DCA mode.

**File:** `src/backtest.py`

The `prep_backtest_args` function at line ~422 builds `bot_params_list` by reading the
`config["bot"]` dict. Because the Rust python.rs parser now accepts the new keys with
defaults, no change is strictly required here — the new keys pass through automatically
via the Python dict. But verify by checking that `bot_params_template` includes the new keys.

**File:** `src/passivbot.py`

The live bot calls entry/close calculation via the Rust extension too. The same routing
logic (Step 5) handles it. No additional changes needed unless live-specific order
placement needs adjustment for market SO orders.

---

## Step 7 — Rebuild and test

```bash
# Rebuild Rust
cd /root/passivbot/passivbot-rust
source ~/.cargo/env
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin build --release 2>&1 | tail -3
source /root/passivbot/venv/bin/activate
pip install target/wheels/passivbot_rust-*.whl --force-reinstall -q

# Run backtest
cd /root/passivbot
echo 1 > /proc/sys/vm/overcommit_memory
python3 src/backtest.py configs/HYPE_long.json -dp
```

Expected: backtest completes in ~0.3s, shows positive ADG, sensible drawdown.

---

## Files NOT to touch

- `src/downloader.py` — BTC patch is already there, don't revert it
- `src/optimize.py` — optimizer works with any bot params, no changes needed
- `passivbot-rust/src/analysis.rs` — metrics calculation, no changes needed
- `passivbot-rust/src/backtest.rs` — backtest loop, no changes needed (routes through entries/closes)
- `passivbot-rust/src/trailing_flip.rs` — trailing logic, not used in DCA mode
