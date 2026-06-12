# Agent Brief — passivbot fork, louisclub/passivbot

## What this repo is

Fork of enarjord/passivbot v7.4.4, hosted at https://github.com/louisclub/passivbot
Working directory: `/root/passivbot`
Branch: `release/v7.4.4`

Your task: implement 3Commas-style DCA orders as described in `FEATURE_SPEC_3COMMAS_DCA.md`.
Read `CODE_MAP.md` for exactly which files to touch and in what order.

---

## VPS environment

- OS: Linux, 1 CPU, 950 MB RAM
- Python: 3.14.4
- Venv: `/root/passivbot/venv` — always activate before running anything
  ```bash
  source /root/passivbot/venv/bin/activate
  ```
- Rust toolchain: installed at `~/.cargo`, already built once
- Git: configured as `louisclub`, credentials stored in `~/.git-credentials`

---

## Critical: OOM fix (must run after every reboot)

The Rust engine uses ~2.5 GB virtual memory. Without this the kernel OOM-kills it:
```bash
echo 1 > /proc/sys/vm/overcommit_memory
```
Does not persist across reboots. Run it before any backtest or optimize.

---

## How to rebuild the Rust extension (required after any .rs file change)

```bash
cd /root/passivbot/passivbot-rust
source ~/.cargo/env
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin build --release 2>&1 | tail -5
source /root/passivbot/venv/bin/activate
pip install target/wheels/passivbot_rust-*.whl --force-reinstall -q
```

Build takes ~2.5 minutes on this VPS. Always reinstall the wheel after building.

---

## How to run a backtest

```bash
cd /root/passivbot
echo 1 > /proc/sys/vm/overcommit_memory
source venv/bin/activate
python3 src/backtest.py configs/HYPE_long.json -dp
```

Backtest runs in ~0.3 seconds once data is cached. The `-dp` flag disables plotting (no display).

---

## How to run the optimizer (test with few iters)

```bash
cd /root/passivbot
echo 1 > /proc/sys/vm/overcommit_memory
source venv/bin/activate
python3 src/optimize.py configs/HYPE_long.json
```

Config has `iters: 100, population_size: 20, n_cpus: 1`. Keep n_cpus at 1 (single CPU VPS).

---

## Historical data already cached

HYPE 1m OHLCV data from Bybit is cached at:
`/root/passivbot/historical_data/ohlcvs_bybit/HYPE/`

Covers 2026-04-06 to 2026-06-10 (~65 days). The backtest config uses `start_date: 2026-04-12`
with warmup, so data is sufficient. Do not re-download unless you change the date range.

Config: `/root/passivbot/configs/HYPE_long.json`

---

## Existing patches already applied (do not revert)

**`src/downloader.py` line ~1338** — skips BTC price download when `use_btc_collateral: false`.
Without this patch the bot downloads BTC data unnecessarily and gets OOM-killed.
```python
use_btc_collateral = bool(require_config_value(config, "backtest.use_btc_collateral"))
if use_btc_collateral:
    # ... fetch BTC
else:
    btc_usd_prices = np.ones(len(timestamps), dtype=np.float64)
```

---

## Git workflow

```bash
cd /root/passivbot
git add <specific files>
git commit -m "your message"
git push origin release/v7.4.4
```

Remote is `origin` = https://github.com/louisclub/passivbot
Upstream (original enarjord) is `upstream` (read-only reference).

---

## Baseline backtest results (before feature, for regression check)

Config: `configs/HYPE_long.json`, 2 months HYPE long-only, $10k balance, 1x exposure

| Metric | Baseline |
|--------|----------|
| ADG | 0.065% |
| Gain (2 months) | 4.3% |
| Worst drawdown | 2.84% |
| Sharpe | 0.10 |
| Loss/profit ratio | 0.0 |

After implementing the feature, run backtest with the new DCA params and confirm results
are sensible (positive ADG, drawdown < 40%, no crashes).
