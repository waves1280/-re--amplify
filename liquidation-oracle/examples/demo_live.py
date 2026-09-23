#!/usr/bin/env python3
"""Live demo — reAmplify Zero-Borrow Cell / vault programme (default).

Illustrates:
  - Registering a new Cell vault programme (ZERO_BORROW)
  - Live vault lifecycle from Babylon Vault Indexer (Zero-Borrow; no HF)
  - Path 1 claim-driven redemption notice
  - BTC Reference Price B.5 watch + Insurance Returns scaffolding
  - Brief note on future Board-authorized Borrow-Enabled mode

Usage:
  pip install -e ".[dev]"
  python examples/demo_live.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reamplify_oracle import (
    CellProgrammeConfig,
    LiquidationOracle,
    OperatingMode,
)
from reamplify_oracle.config import OracleConfig
from reamplify_oracle.logging_setup import setup_logging

# Docs / testnet illustration vault (Zero-Borrow lifecycle)
SAMPLE_VAULT = "0x002f198c46664c28f0685ba86303256e9833344a54c7b4e34483e7805f5b8d4a"
SAMPLE_DEPOSITOR = "0x106d71c740aeebf6e72f06dad4129651dc65d810"


def main() -> None:
    cfg_path = ROOT / "config.example.yaml"
    config = OracleConfig.from_file(cfg_path) if cfg_path.exists() else OracleConfig()
    config = OracleConfig.from_env(config)
    # Demo always leads with Zero-Borrow unless user explicitly overrides
    if config.mode != OperatingMode.ZERO_BORROW:
        print(f"Note: config mode={config.mode.value}; demo forces ZERO_BORROW primary path.")
        config.mode = OperatingMode.ZERO_BORROW

    setup_logging(config.log_level, json_logs=config.json_logs)

    print("=" * 72)
    print("reAmplify Liquidation Oracle — Zero-Borrow Cell demo")
    print(f"Indexer: {config.indexer.url}")
    print(f"User-Agent: {config.indexer.user_agent}")
    print(f"Mode: {config.mode.value} (default for new reAmplify vault)")
    print("=" * 72)

    with LiquidationOracle(config) as oracle:
        # 1) Register Cell programme for a new vault
        programme = CellProgrammeConfig(
            cell_id=config.cell.cell_id,
            name=config.cell.name,
            mode=OperatingMode.ZERO_BORROW,
            depositor_address=config.cell.depositor_address or SAMPLE_DEPOSITOR,
            vault_ids=config.cell.vault_ids or [SAMPLE_VAULT],
            board_btc_baseline_usd=config.btc_reference.baseline_usd,
            path1_notice_calendar_days=config.timing.path1_notice_calendar_days,
            notes=[
                "reAmplify vault / Cell programme — Zero-Borrow posture (B.1.1).",
                "Internal HF monitoring only if Board authorizes BORROW_ENABLED (B.1.2).",
            ],
        )
        oracle.register_cell(programme)
        print("\n[Cell programme registered]")
        print(json.dumps(programme.to_dict(), indent=2))

        # 2) Indexer freshness
        meta = oracle.indexer.get_meta()
        print("\n[Indexer _meta]")
        print(json.dumps({
            "chain_id": meta.chain_id,
            "block_number": meta.block_number,
            "block_timestamp": meta.block_timestamp,
        }, indent=2))

        # 3) Evaluate vault lifecycle (primary Zero-Borrow path)
        print(f"\n[evaluate_vault {SAMPLE_VAULT}]")
        report = oracle.evaluate_vault(SAMPLE_VAULT, cell_id=programme.cell_id)
        out = report.to_dict()
        # Trim recent activities for readability in stdout
        print(json.dumps(out, indent=2, default=str))

        # 4) Cell-level evaluation
        print("\n[evaluate_cell]")
        cell_report = oracle.evaluate_cell(programme.cell_id)
        print(json.dumps({
            "zone": cell_report.zone.value,
            "operating_mode": cell_report.operating_mode,
            "on_chain_liquidation_risk": cell_report.on_chain_liquidation_risk,
            "internal_hf_applicable": cell_report.internal_hf_applicable,
            "vault_count": len(cell_report.vaults),
            "vault_statuses": [v.status for v in cell_report.vaults],
            "btc_reference_usd": cell_report.btc_reference.price_usd if cell_report.btc_reference else None,
            "recommend_suspend_new_policies": (
                cell_report.btc_reference.recommend_suspend_new_policies
                if cell_report.btc_reference else False
            ),
            "alerts": cell_report.alerts,
            "notes": cell_report.notes,
        }, indent=2))

        # 5) Path 1 — primary redemption for Zero-Borrow
        p1 = oracle.redemption.open_path1_notice(
            depositor_address=programme.depositor_address,
            vault_ids=programme.vault_ids,
            claim_exceeds_premium_reserve=True,
            dual_signoff_board=True,
            dual_signoff_commission=True,
            metadata={"demo": True, "path": "claim-driven ordinary redemption"},
        )
        print("\n[Path 1 claim-driven notice (primary for Zero-Borrow)]")
        print(json.dumps(p1.to_dict(), indent=2, default=str))

        # 6) BTC B.5 watch + Insurance Returns (not mixed with BTC price)
        print("\n[BTC Reference Price B.5]")
        if cell_report.btc_reference:
            br = cell_report.btc_reference
            print(json.dumps({
                "spot_usd": br.price_usd,
                "sources": br.sources,
                "baseline_usd": br.baseline_usd,
                "decline_vs_baseline_pct": br.decline_vs_baseline_pct,
                "recommend_suspend_new_policies": br.recommend_suspend_new_policies,
                "note": br.note,
            }, indent=2))

        ir = oracle.insurance.submit_monthly("2026-09", 100_000.0, 8_000.0, 500_000.0)
        print("\n[Insurance Returns scaffolding (separate from BTC price / HF)]")
        print(json.dumps(ir.to_dict(), indent=2))

        # 7) Brief future-mode note
        print("\n[Borrow-Enabled — future Board-authorized only (B.1.2)]")
        print(
            "Internal HF / debt reconstruction / A.4 zones remain in-package but are\n"
            "quarantined. Call oracle.set_mode(BORROW_ENABLED) only after Board approval,\n"
            "then oracle.evaluate_depositor_borrow_enabled(address). Not the default path\n"
            "for reAmplify's new vault."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
