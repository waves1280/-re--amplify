# ReamplifyRiskOracle (on-chain monitoring feed)

Solidity contracts that let a Python keeper publish **off-chain** Internal HF /
zone snapshots so Cell programmes and downstream apps can **read** them on-chain.

## What this is / is not

| This contract | Spoke / Babylon liquidation |
|---------------|------------------------------|
| reAmplify **monitoring** oracle | Uses **Babylon / Chainlink** price feeds |
| Cell ops + app consumers | On-chain liquidatable when Spoke HF &lt; 1.0 |
| Keeper-updated snapshots | Independent of this contract |

**Do not** treat `ReamplifyRiskOracle` as a Chainlink Aggregator substitute.
Spoke liquidation pricing is unchanged.

## Layout

```
contracts/
  IReamplifyRiskOracle.sol   # interface + RiskZone + RiskSnapshot
  ReamplifyRiskOracle.sol    # Ownable + keepers mapping
  foundry.toml               # optional forge layout
  README.md
```

## Snapshot fields

| Field | Type | Notes |
|-------|------|-------|
| `vaultId` | `bytes32` | Babylon vault id (hex → bytes32) |
| `depositor` | `address` | Vault depositor |
| `internalHF` | `uint256` | 1e18 precision; **`type(uint256).max` = infinite / no debt (B.1 Zero-Borrow)** |
| `zone` | `RiskZone` / `uint8` | `0 ZERO_BORROW`, `1 GREEN`, `2 RED`, `3 CRITICAL` |
| `btcRefPriceUsd` | `uint256` | USD with **8 decimals**; `0` if unused |
| `recommendSuspendNewPolicies` | `bool` | B.5 crash watch |
| `updatedAt` | `uint64` | `block.timestamp` at write |
| `indexerBlock` | `uint64` | Last indexer block observed off-chain |

## Roles

- **Owner** — `transferOwnership`, `setKeeper(address, bool)`.
- **Keepers** — may call `updateRisk` / `updateRiskBatch`. Owner is always allowed.
- **Consumers** — read `getRisk(bytes32)` or `getRiskByDepositor(address)`.

## Deploy (Foundry)

```bash
cd contracts
forge build
forge create ReamplifyRiskOracle \
  --constructor-args <OWNER_ADDRESS> \
  --rpc-url $RPC_URL \
  --private-key $DEPLOYER_KEY
```

Then register keepers:

```solidity
oracle.setKeeper(keeperAddress, true);
```

Set env for the Python relayer:

```bash
export REAMPLIFY_RISK_ORACLE_ADDRESS=0x...
export REAMPLIFY_KEEPER_KEY=0x...   # never commit / never log
export REAMPLIFY_RPC_URL=https://...
# live send only when BOTH are set:
export REAMPLIFY_KEEPER_LIVE=1
```

## Consumer read example

```solidity
IReamplifyRiskOracle.RiskSnapshot memory s = oracle.getRisk(vaultId);
require(s.updatedAt + maxStaleness >= block.timestamp, "stale");
if (s.zone == IReamplifyRiskOracle.RiskZone.CRITICAL) {
    // Cell ops reaction — NOT Spoke liquidation
}
```
