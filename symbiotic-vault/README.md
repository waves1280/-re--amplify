# Symbiotic Vault V2 — reAmplify WBTC

Deploy config for the **reAmplify WBTC** Symbiotic Vault V2 (`raWBTC`) on Ethereum mainnet.

This folder is an **overlay** for [symbioticfi/core](https://github.com/symbioticfi/core), not a copy of it:

| File | Purpose |
|---|---|
| [`REAMPLIFY_DEPLOY.md`](./REAMPLIFY_DEPLOY.md) | Full instructions: parameters, dry-run, broadcast, UI metadata, post-deploy |
| [`script/DeployVaultV2.s.sol`](./script/DeployVaultV2.s.sol) | Configured deploy script (drop-in replacement for core's `script/DeployVaultV2.s.sol`) |
| [`DeployVaultV2.reamplify.patch`](./DeployVaultV2.reamplify.patch) | Same change as a `git apply`-able diff vs upstream `25a065a` |
| [`.env.example`](./.env.example) | Env var names (`ETH_RPC_URL`, `ETHERSCAN_API_KEY`) — never commit a real `.env` |

Quick start:

```bash
git clone --recurse-submodules https://github.com/symbioticfi/core.git symbiotic-core
cp symbiotic-vault/script/DeployVaultV2.s.sol symbiotic-core/script/DeployVaultV2.s.sol
cd symbiotic-core && forge build
forge script script/DeployVaultV2.s.sol:DeployVaultV2Script --rpc-url "$ETH_RPC_URL" --ledger   # dry-run, no --broadcast
```

The script imports `./base/DeployVaultV2Base.sol` from core, so it will not compile on its own inside this repo.
