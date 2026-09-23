#!/usr/bin/env python3
"""Dry-run demo: evaluate a vault/depositor and print the on-chain updateRisk payload.

Does NOT send a transaction. Speaks to the Babylon indexer + BTC reference sources,
then encodes ReamplifyRiskOracle.updateRisk calldata.

Usage:
  pip install -e ".[dev,keeper]"
  python examples/demo_keeper_dry_run.py
  python examples/demo_keeper_dry_run.py --vault 0x002f198c…
  python examples/demo_keeper_dry_run.py --depositor 0x106d71c7…
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reamplify_oracle import LiquidationOracle
from reamplify_oracle.config import OracleConfig
from reamplify_oracle.keeper import RiskOracleKeeper
from reamplify_oracle.logging_setup import setup_logging

SAMPLE_VAULT = "0x002f198c46664c28f0685ba86303256e9833344a54c7b4e34483e7805f5b8d4a"
SAMPLE_DEPOSITOR = "0x106d71c740aeebf6e72f06dad4129651dc65d810"


def main() -> None:
    parser = argparse.ArgumentParser(description="Keeper dry-run demo")
    parser.add_argument("--vault", default=SAMPLE_VAULT)
    parser.add_argument("--depositor", default=None)
    parser.add_argument(
        "--contract",
        default=None,
        help="REAMPLIFY_RISK_ORACLE_ADDRESS (placeholder OK for dry-run encode)",
    )
    args = parser.parse_args()

    cfg_path = ROOT / "config.example.yaml"
    config = OracleConfig.from_file(cfg_path) if cfg_path.exists() else OracleConfig()
    config = OracleConfig.from_env(config)
    setup_logging(config.log_level, json_logs=config.json_logs)

    contract = args.contract or config_env_contract() or ("0x" + ("11" * 20))

    print("=" * 72)
    print("reAmplify Risk Oracle Keeper — DRY RUN")
    print("Monitoring feed only — does NOT replace Spoke/Chainlink liquidation pricing.")
    print(f"Contract (encode target): {contract}")
    print("=" * 72)
    sys.stdout.flush()

    with LiquidationOracle(config) as oracle:
        keeper = RiskOracleKeeper(
            config,
            oracle=oracle,
            contract_address=contract,
            dry_run=True,
        )
        try:
            # Force web3 ABI codec without needing a live RPC
            try:
                from web3 import Web3

                keeper._web3 = Web3()  # noqa: SLF001
            except ImportError:
                print(
                    "\n[!] web3 not installed — install with: pip install -e '.[keeper]'\n"
                    "    Falling back to snapshot dict only (no calldata).\n"
                )
                if args.depositor:
                    snaps = keeper.build_snapshots_for_depositor(args.depositor)
                else:
                    snaps = keeper.build_snapshots_for_vault(args.vault)
                print(json.dumps([s.to_dict() for s in snaps], indent=2))
                return

            if args.depositor:
                print(f"\nEvaluating depositor {args.depositor} …")
                result = keeper.publish_depositor(args.depositor)
            else:
                print(f"\nEvaluating vault {args.vault} …")
                result = keeper.publish_vault(args.vault)
            print("\n[Would-be on-chain update]")
            print(json.dumps(result, indent=2, default=str))
        finally:
            keeper.close()


def config_env_contract() -> str | None:
    import os

    return os.getenv("REAMPLIFY_RISK_ORACLE_ADDRESS")


if __name__ == "__main__":
    main()
