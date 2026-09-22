# reAmplify Liquidation Oracle

Python package for Joshua / reAmplify’s **new vault** programme against the
[Babylon TBV Vault Indexer](https://babylon-vault-indexer-api.testnet.babylonlabs.io/) GraphQL API.

## Default posture: ZERO_BORROW

reAmplify’s vault is **Zero-Borrow by default** (policy **B.1.1 / A.2.1**):

- **No Aave required.** Monitoring uses indexer `vault` / `vaults` / `vaultActivity` / provider / fees.
- **No on-chain liquidation risk** from borrowing while in Zero-Borrow.
- **Internal HF is N/A** unless the Board later authorizes **BORROW_ENABLED (B.1.2)**.
- Primary redemption path is **Path 1** (claim-driven, ≥30 days notice).

Borrow-Enabled / Internal HF code remains in-package but is **quarantined** and must not be the main ops path.

## Quick start

```bash
cd /workspace/reamplify-liquidation-oracle
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Live Zero-Borrow demo (custom User-Agent — required to avoid 403)
python examples/demo_live.py

pytest -q
```

| Env | Meaning |
|-----|---------|
| `REAMPLIFY_MODE` | `ZERO_BORROW` (default) or `BORROW_ENABLED` (Board only) |
| `REAMPLIFY_INDEXER_URL` | GraphQL endpoint |
| `REAMPLIFY_USER_AGENT` | Custom UA (default clients get **403**) |
| `REAMPLIFY_BTC_BASELINE_USD` | Board-approved BTC baseline (B.5) |
| `REAMPLIFY_LOG_LEVEL` | `INFO` / `DEBUG` |

See `config.example.yaml` for Cell programme (`cell.vault_ids`, depositor, baselines).

## What Zero-Borrow monitors (A.2.1 / B.1.1)

| Signal | Indexer / module |
|--------|------------------|
| Vault lifecycle | `vault` / `vaults` — status pending → … → available → redeemed / liquidated / expired / … |
| Activities | `vaultActivitys` — **deposit / redeem / liquidation / claim_expired** (not borrow/repay) |
| Provider & fees | `vaultProvider`, `vaultFeeEscrow`, `feeConfigs` |
| Peg-in risk | `ackCount`, `expiredAt` / `expirationReason`, `claimExpiredUntil` |
| BTC Reference Price | CoinGecko + Coinbase (≥2); ≥50% vs baseline → suspend new policies (**B.5**) — **not** for Insurance Returns |
| Insurance Returns | Scaffolding only — `pending_actuarial_confirmation` until External Actuary |

Facade API:

```python
from reamplify_oracle import LiquidationOracle, CellProgrammeConfig, OperatingMode
from reamplify_oracle.config import OracleConfig

config = OracleConfig.from_file("config.example.yaml")  # mode: ZERO_BORROW

with LiquidationOracle(config) as oracle:
    programme = CellProgrammeConfig(
        cell_id="reamplify-cell-1",
        name="reAmplify Cell",
        mode=OperatingMode.ZERO_BORROW,
        depositor_address="0x106d…",
        vault_ids=["0x002f198c…"],
        board_btc_baseline_usd=100_000,
    )
    oracle.register_cell(programme)

    vault_report = oracle.evaluate_vault("0x002f198c…", cell_id=programme.cell_id)
    cell_report = oracle.evaluate_cell(programme.cell_id)
    # zone == ZERO_BORROW; internal_hf_applicable == False; on_chain_liquidation_risk == False

    p1 = oracle.redemption.open_path1_notice(
        depositor_address=programme.depositor_address,
        vault_ids=programme.vault_ids,
        claim_exceeds_premium_reserve=True,
        dual_signoff_board=True,
        dual_signoff_commission=True,
    )
```

## Module → policy map (Zero-Borrow first)

| Module | Policy | Role |
|--------|--------|------|
| `cell_monitor.py` | A.2.1 / B.1.1 | **Primary** Cell/vault lifecycle monitor |
| `indexer_client.py` | A.1 / A.2.1 | GraphQL client (UA, paging); vault* primary; aave* optional |
| `price_oracle.py` | A.3.4 / B.5 | BTC reference (≥2 sources); suspend watch |
| `insurance_returns.py` | A.3.2 | Premiums/claims/reserves scaffolding |
| `redemption.py` | Part B | Path 1 primary; Path 2 rare; Path 3 WOTS |
| `oracle.py` | Facade | `evaluate_vault` / `evaluate_cell`; Borrow-Enabled quarantined |
| `config.py` | B.1 | Modes + Cell programme YAML |

### Borrow-Enabled only (optional, Board-authorized B.1.2)

Do **not** use for the new vault unless the Board flips mode.

| Module | Policy | Role |
|--------|--------|------|
| `health_factor.py` | A.3.2(c) | Internal HF formula |
| `escalation.py` | A.4 | Green / Red / Critical zones |
| `divergence.py` | A.5 | Internal vs Spoke HF divergence |
| `spoke_hf.py` | A.5 | Stub Spoke HF provider (no fabricated values) |

```python
oracle.set_mode(OperatingMode.BORROW_ENABLED)  # Board authorization required
hf = oracle.evaluate_depositor_borrow_enabled("0x…")
```

If `aavePosition` is null / no debt → report **Zero-Borrow posture** (never CRITICAL HF).

## Redemption (Part B)

| Path | When | Controls |
|------|------|----------|
| **1** Ordinary / claim-driven | **Primary** for Zero-Borrow | ≥30 calendar days; dual-signoff; claim exceeds premium reserve |
| **2** Liquidation-triggered | Borrow-Enabled **or** unexpected `liquidated` on indexer (rare in Zero-Borrow) | Same-day Board+Commission; post-mortem ≤5 BD; auto-revert Zero-Borrow |
| **3** WOTS self-claim | Custodianship tracking | Multi-person; **no secrets in code** |

Timing constants: CSA Support Notice **2 BD**, TBV challenge **~3 days**, peg-in refund **~14 days**.

## Indexer notes / gaps

- Custom **User-Agent** required (else 403).
- BigInts are **strings**; `limit` ≤ 1000; page with `offset`.
- **No native HF field** — HF only if Borrow-Enabled + off-indexer compute / Spoke adapter.
- Plural quirk: `aaveVaultStatuss` (unused in Zero-Borrow path).
- reAmplify new vault does **not** depend on Aave entities.

## Package layout

```
reamplify-liquidation-oracle/
  pyproject.toml
  requirements.txt
  config.example.yaml
  README.md
  reamplify_oracle/
  examples/demo_live.py
  tests/
```

## License

Proprietary — reAmplify / Joshua Vizer.
