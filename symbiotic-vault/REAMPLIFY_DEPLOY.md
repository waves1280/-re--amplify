# reAmplify WBTC Vault V2 — Deploy Package

Ready-to-run Symbiotic Vault V2 deploy config for **reAmplify** on **Ethereum mainnet**.

Overlay for [symbioticfi/core](https://github.com/symbioticfi/core): clone core, drop in the configured `script/DeployVaultV2.s.sol` from this folder, then run `forge script`.

---

## Configured parameters

| Setting | Value |
|---|---|
| Chain | Ethereum mainnet (`chainid = 1`) |
| Share token name | `reAmplify WBTC` |
| Share token symbol | `raWBTC` |
| Collateral / ASSET (WBTC) | `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599` |
| OWNER (all roles) | `0xa2163bff0F2EBD4894aF901C642E88dCe9FC3574` |
| Deposit limit | `0` (unlimited; `isDepositLimit = false`) |
| Deposit whitelist | `false` |
| Adapters at launch | **None** |
| UI | None (on-chain only) |

Configured file: [`script/DeployVaultV2.s.sol`](./script/DeployVaultV2.s.sol) (diff vs upstream: [`DeployVaultV2.reamplify.patch`](./DeployVaultV2.reamplify.patch))

All VaultV2 and Universal Delegator role holders are set to `OWNER` (default admin, fees, deposit limit/whitelist, allocate/deallocate, add/remove/swap adapters, adapter limits, auto-allocate).

### Mainnet addresses (reference)

| Contract | Address |
|---|---|
| Vault Factory | `0xAEb6bdd95c502390db8f52c8909F703E9Af6a346` |
| WBTC | `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599` |
| Owner | `0xa2163bff0F2EBD4894aF901C642E88dCe9FC3574` |

The deploy script resolves the factory via `SymbioticCoreConstants.core().vaultFactory` when `block.chainid == 1`.

---

## Setup (this folder is an overlay, not the full core repo)

This directory contains **only** the reAmplify-specific files. The Symbiotic core contracts, libraries and build tooling live upstream in [symbioticfi/core](https://github.com/symbioticfi/core) and are not vendored here.

Prepared and built against upstream commit `25a065a3dd71150a588162bd2ad4833bbd4e2423`.

```bash
# 1. Clone Symbiotic core with submodules
git clone --recurse-submodules https://github.com/symbioticfi/core.git symbiotic-core
cd symbiotic-core
git checkout 25a065a3dd71150a588162bd2ad4833bbd4e2423   # optional: pin to the tested commit
git submodule update --init --recursive

# 2. Overlay the reAmplify configured deploy script (replaces upstream's template)
cp /path/to/-re--amplify/symbiotic-vault/script/DeployVaultV2.s.sol script/DeployVaultV2.s.sol
#    or, equivalently, apply the patch:
#    git apply /path/to/-re--amplify/symbiotic-vault/DeployVaultV2.reamplify.patch

# 3. Build
forge build
```

All `forge script` commands below are run from the root of that `symbiotic-core` clone.

---

## Prerequisites

- [Foundry](https://getfoundry.sh/) (`forge`, `cast`)
- An Ethereum mainnet RPC URL
- The private key (or hardware wallet) for the account that will **pay gas** for the factory `create` call  
  - **Do not commit private keys.** Prefer env vars / keystore / `--ledger` / `--trezor`.

---

## Adapters (not required to launch)

**The vault can accept WBTC deposits with zero adapters.** Deposited capital stays **idle** in the vault until the curator adds adapters via the Universal Delegator and calls allocate (e.g. `AllocateAdapters` / allocateAll-style flows in `script/actions/v2/`).

Adapters are **not** required to launch. Add them later when ready (Aave, Morpho, ERC4626, App, etc.) using:

- [`script/actions/v2/AddAdapter.s.sol`](https://github.com/symbioticfi/core/blob/main/script/actions/v2/AddAdapter.s.sol)
- [`script/actions/v2/SetAdapterLimits.s.sol`](https://github.com/symbioticfi/core/blob/main/script/actions/v2/SetAdapterLimits.s.sol)
- [`script/actions/v2/AllocateAdapters.s.sol`](https://github.com/symbioticfi/core/blob/main/script/actions/v2/AllocateAdapters.s.sol)

See the upstream [README](https://github.com/symbioticfi/core/blob/main/README.md) “Interact with Vaults” section.

---

## Dry-run (simulation, no broadcast)

Simulates the deploy against mainnet state. **Does not spend gas.**

```bash
cd symbiotic-core   # your symbioticfi/core clone with the overlay applied

# Option A: private key in env (never commit .env)
export ETH_RPC_URL="https://eth-mainnet.YOUR_PROVIDER/..."
export PRIVATE_KEY="0x..."   # gas payer; do not commit

forge script script/DeployVaultV2.s.sol:DeployVaultV2Script \
  --rpc-url "$ETH_RPC_URL" \
  --private-key "$PRIVATE_KEY"
```

Or without `--private-key` if you only want a local simulation with a dummy sender (may fail signature/broadcast steps differently). Prefer the dry-run above **without** `--broadcast`.

Hardware wallet dry-run example:

```bash
forge script script/DeployVaultV2.s.sol:DeployVaultV2Script \
  --rpc-url "$ETH_RPC_URL" \
  --ledger
```

Expected console output on success (addresses will differ):

```text
Deployed VaultV2
    vault:0x...
    delegator:0x...
```

---

## Broadcast (live mainnet deploy — spends gas)

**Only when intentionally ready to deploy.** This package was prepared without broadcasting.

```bash
cd symbiotic-core   # your symbioticfi/core clone with the overlay applied

export ETH_RPC_URL="https://eth-mainnet.YOUR_PROVIDER/..."
export PRIVATE_KEY="0x..."   # gas payer; do not commit

forge script script/DeployVaultV2.s.sol:DeployVaultV2Script \
  --rpc-url "$ETH_RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --broadcast \
  --verify \
  -vvvv
```

Optional: set `ETHERSCAN_API_KEY` (see [`.env.example`](./.env.example)) for verification.

Save the printed `vault` and `delegator` addresses after success.

---

## Symbiotic UI visibility

Deploying on-chain does **not** automatically list the vault on [app.symbiotic.fi](https://app.symbiotic.fi).

To appear in the UI, submit curator/vault metadata via PR:

- Docs: [Submit Metadata (curators)](https://docs.symbiotic.fi/integrate/curators/submit-metadata)
- Mainnet metadata repo: [symbioticfi/metadata-mainnet](https://github.com/symbioticfi/metadata-mainnet)
- After opening the PR, email the PR link to `verify@symbiotic.fi` from an official business domain matching the entity website.

Suggested `vaultType` for this collateral: `btc-restaking`.

---

## Post-deploy checklist (optional)

1. Record `vault` + `delegator` addresses from forge logs.
2. Confirm `asset()` is WBTC and `owner`/roles match `0xa2163bff0F2EBD4894aF901C642E88dCe9FC3574`.
3. (Optional) Deposit a small WBTC amount — capital remains idle until adapters are added and allocated.
4. Open metadata PR when ready for `app.symbiotic.fi`.
5. Later: add adapters → set limits → allocate.

---

## Safety notes

- **Do not broadcast** unless you intend to pay mainnet gas.
- **Do not commit** private keys, `.env`, or broadcast artifacts with secrets.
- Never commit `broadcast/`, `.env`, or keystore files from your core clone.
