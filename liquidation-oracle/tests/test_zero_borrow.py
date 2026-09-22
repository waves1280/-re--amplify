"""Zero-Borrow Cell / vault evaluation — no aavePosition, never CRITICAL."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from reamplify_oracle.cell_monitor import (
    CellProgrammeConfig,
    CellVaultMonitor,
    ZERO_BORROW_ACTIVITY_TYPES,
)
from reamplify_oracle.config import OperatingMode, OracleConfig
from reamplify_oracle.models import BtcReferencePrice, EscalationZone
from reamplify_oracle.oracle import LiquidationOracle


def _btc_ref(price: float = 90_000.0) -> BtcReferencePrice:
    return BtcReferencePrice(
        price_usd=price,
        sources={"coingecko": price, "coinbase": price},
        aggregate_method="median",
        baseline_usd=100_000.0,
        decline_vs_baseline_pct=10.0,
        recommend_suspend_new_policies=False,
        as_of=datetime.now(timezone.utc),
    )


def test_zero_borrow_activity_types_exclude_borrow_repay():
    assert "deposit" in ZERO_BORROW_ACTIVITY_TYPES
    assert "redeem" in ZERO_BORROW_ACTIVITY_TYPES
    assert "liquidation" in ZERO_BORROW_ACTIVITY_TYPES
    assert "borrow" not in ZERO_BORROW_ACTIVITY_TYPES
    assert "repay" not in ZERO_BORROW_ACTIVITY_TYPES


def test_evaluate_vault_without_aave_is_zero_borrow_not_critical():
    indexer = MagicMock()
    indexer.get_meta.return_value = MagicMock(
        chain_id="11155111", block_number=1, block_timestamp=2, raw_status={}
    )
    indexer.get_vault.return_value = {
        "id": "0xv",
        "status": "available",
        "amount": "1000000",
        "depositor": "0xdep",
        "vaultProvider": "0xprov",
        "vaultProviderCommissionBps": 100,
        "ackCount": 6,
        "inUse": True,
        "applicationEntryPoint": "0xe",
        "pendingAt": "1",
        "verifiedAt": "2",
        "activatedAt": "3",
        "expiredAt": None,
        "expirationReason": None,
        "claimExpiredUntil": None,
        "peginTxHash": "0xpeg",
    }
    indexer.get_vault_provider.return_value = {"id": "0xprov", "name": "TestVP"}
    indexer.get_vault_fee_escrow.return_value = None
    indexer.iter_vault_activities.return_value = iter(
        [
            {
                "type": "deposit",
                "amount": "1000000",
                "timestamp": "3",
                "depositor": "0xdep",
            }
        ]
    )

    price = MagicMock()
    price.fetch.return_value = _btc_ref()

    monitor = CellVaultMonitor(OracleConfig(), indexer, price)
    report = monitor.evaluate_vault("0xv")

    assert report.zone == EscalationZone.ZERO_BORROW
    assert report.zone != EscalationZone.CRITICAL
    assert report.on_chain_liquidation_risk is False
    assert report.internal_hf_applicable is False
    assert report.vaults[0].status == "available"
    assert report.vaults[0].amount_sats == 1_000_000


def test_evaluate_cell_registers_and_lists_vaults():
    indexer = MagicMock()
    indexer.get_meta.return_value = MagicMock(
        chain_id="1", block_number=1, block_timestamp=1, raw_status={}
    )
    indexer.get_vault.return_value = {
        "id": "0xv1",
        "status": "available",
        "amount": "500000",
        "depositor": "0xdep",
        "vaultProvider": None,
        "vaultProviderCommissionBps": 0,
        "ackCount": 1,
        "inUse": False,
        "applicationEntryPoint": None,
        "pendingAt": None,
        "verifiedAt": None,
        "activatedAt": None,
        "expiredAt": None,
        "expirationReason": None,
        "claimExpiredUntil": None,
        "peginTxHash": None,
    }
    indexer.get_vault_provider.return_value = None
    indexer.get_vault_fee_escrow.return_value = None
    indexer.iter_vault_activities.return_value = iter([])
    price = MagicMock()
    price.fetch.return_value = _btc_ref()

    cfg = OracleConfig()
    monitor = CellVaultMonitor(cfg, indexer, price)
    prog = CellProgrammeConfig(
        cell_id="c1",
        name="Cell",
        mode=OperatingMode.ZERO_BORROW,
        vault_ids=["0xv1"],
    )
    monitor.register_cell(prog)
    report = monitor.evaluate_cell("c1")
    assert report.scope == "cell"
    assert report.zone == EscalationZone.ZERO_BORROW
    assert len(report.vaults) == 1


def test_borrow_enabled_entrypoint_blocked_in_zero_borrow():
    oracle = LiquidationOracle(
        OracleConfig(),
        indexer=MagicMock(),
        price_oracle=MagicMock(),
    )
    with pytest.raises(RuntimeError, match="BORROW_ENABLED"):
        oracle.evaluate_depositor_borrow_enabled("0xabc")


def test_no_position_borrow_path_not_critical():
    """When Board enables borrow but depositor has no aavePosition/debt → ZERO_BORROW zone."""
    from reamplify_oracle.health_factor import build_hf_report
    from reamplify_oracle.models import PositionState

    position = PositionState(
        depositor_address="0xabc",
        proxy_contract=None,
        total_collateral_sats=0,
        collaterals=[],
        debt_by_reserve=[],
        activity_summary={},
        has_liquidation_activity=False,
        liquidated_vault_ids=[],
        freshness=None,
    )
    report = build_hf_report(
        position,
        mode=OperatingMode.ZERO_BORROW,
        collateral_factor=0.0,
        btc_ref=_btc_ref(),
        escalation=OracleConfig().escalation,
    )
    assert report.zone == EscalationZone.ZERO_BORROW
    assert report.internal_hf is None
