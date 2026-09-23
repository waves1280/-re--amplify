"""Unit tests for on-chain risk oracle keeper (mocked web3, no RPC)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

try:
    from web3 import Web3
except ImportError:  # pragma: no cover
    Web3 = None  # type: ignore

from reamplify_oracle.cell_monitor import CellProgrammeConfig, VaultLifecycleSnapshot, ZeroBorrowReport
from reamplify_oracle.config import OperatingMode
from reamplify_oracle.keeper import (
    MAX_UINT256,
    ZONE_TO_UINT8,
    RiskOracleKeeper,
    encode_btc_ref_usd,
    encode_internal_hf,
    load_abi,
    normalize_address,
    snapshot_from_hf_report,
    snapshot_from_zero_borrow,
    vault_id_to_bytes32,
    zone_to_uint8,
)
from reamplify_oracle.models import (
    BtcReferencePrice,
    EscalationZone,
    HealthFactorReport,
    IndexerFreshness,
)


SAMPLE_VAULT = "0x002f198c46664c28f0685ba86303256e9833344a54c7b4e34483e7805f5b8d4a"
SAMPLE_DEPOSITOR = "0x106d71c740aeebf6e72f06dad4129651dc65d810"


def _btc(price: float = 95_000.0, suspend: bool = False) -> BtcReferencePrice:
    return BtcReferencePrice(
        price_usd=price,
        sources={"coingecko": price, "coinbase": price},
        aggregate_method="median",
        baseline_usd=100_000.0,
        decline_vs_baseline_pct=(100_000.0 - price) / 100_000.0 * 100.0,
        recommend_suspend_new_policies=suspend,
        as_of=datetime.now(timezone.utc),
    )


def _vault_snap(vault_id: str = SAMPLE_VAULT) -> VaultLifecycleSnapshot:
    return VaultLifecycleSnapshot(
        vault_id=vault_id,
        status="available",
        amount_sats=100_000_000,
        amount_btc=1.0,
        amount_usd=95_000.0,
        depositor=SAMPLE_DEPOSITOR,
        vault_provider=None,
        vault_provider_name=None,
        vault_provider_commission_bps=None,
        ack_count=5,
        in_use=False,
        application_entry_point=None,
        pending_at=None,
        verified_at=None,
        activated_at=None,
        expired_at=None,
        expiration_reason=None,
        claim_expired_until=None,
        pegin_tx_hash=None,
        fee_escrow=None,
        activity_summary={"deposit": 1},
        recent_activities=[],
        lifecycle_alerts=[],
        is_liquidated=False,
        is_terminal=False,
    )


def _zb_report() -> ZeroBorrowReport:
    return ZeroBorrowReport(
        scope="vault",
        cell=CellProgrammeConfig(
            cell_id="test",
            name="test",
            mode=OperatingMode.ZERO_BORROW,
            depositor_address=SAMPLE_DEPOSITOR,
            vault_ids=[SAMPLE_VAULT],
        ),
        operating_mode=OperatingMode.ZERO_BORROW.value,
        zone=EscalationZone.ZERO_BORROW,
        on_chain_liquidation_risk=False,
        internal_hf_applicable=False,
        vaults=[_vault_snap()],
        btc_reference=_btc(),
        freshness=IndexerFreshness(
            raw_status={},
            chain_id="31337",
            block_number=12_345_678,
        ),
        notes=["Zero-Borrow posture"],
    )


def test_zone_mapping():
    assert zone_to_uint8(EscalationZone.ZERO_BORROW) == 0
    assert zone_to_uint8(EscalationZone.GREEN) == 1
    assert zone_to_uint8(EscalationZone.RED) == 2
    assert zone_to_uint8(EscalationZone.CRITICAL) == 3
    assert zone_to_uint8(EscalationZone.UNKNOWN) == 0
    assert zone_to_uint8("GREEN") == 1
    assert ZONE_TO_UINT8[EscalationZone.CRITICAL] == 3


def test_encode_internal_hf_infinite_is_max_uint():
    assert encode_internal_hf(None) == MAX_UINT256
    assert encode_internal_hf(float("inf")) == MAX_UINT256
    assert encode_internal_hf(2.0) == 2 * 10**18
    assert encode_internal_hf(1.5) == int(1.5 * 10**18)


def test_encode_btc_ref_8_decimals():
    assert encode_btc_ref_usd(None) == 0
    assert encode_btc_ref_usd(95_000.0) == 95_000 * 10**8
    assert encode_btc_ref_usd(0) == 0


def test_vault_id_to_bytes32():
    b, h = vault_id_to_bytes32(SAMPLE_VAULT)
    assert len(b) == 32
    assert h == SAMPLE_VAULT.lower()
    assert b.hex() == SAMPLE_VAULT[2:].lower()


def test_normalize_address():
    assert Web3 is not None and normalize_address(SAMPLE_DEPOSITOR) == Web3.to_checksum_address(SAMPLE_DEPOSITOR)
    assert normalize_address(None) == "0x" + ("00" * 20)


def test_snapshot_from_zero_borrow_sets_max_hf():
    snaps = snapshot_from_zero_borrow(_zb_report())
    assert len(snaps) == 1
    s = snaps[0]
    assert s.internal_hf == MAX_UINT256
    assert s.zone == 0
    assert s.zone_name == "ZERO_BORROW"
    assert Web3 is not None and s.depositor == Web3.to_checksum_address(SAMPLE_DEPOSITOR)
    assert s.indexer_block == 12_345_678
    assert s.btc_ref_price_usd == 95_000 * 10**8
    assert s.recommend_suspend_new_policies is False


def test_snapshot_from_hf_report_green():
    report = HealthFactorReport(
        depositor_address=SAMPLE_DEPOSITOR,
        operating_mode=OperatingMode.BORROW_ENABLED.value,
        internal_hf=3.5,
        zone=EscalationZone.GREEN,
        total_collateral_btc=1.0,
        total_collateral_usd=95_000.0,
        collateral_factor=0.78,
        total_debt_usd=20_000.0,
        btc_reference=_btc(),
        notes=[],
    )
    s = snapshot_from_hf_report(report)
    assert s.zone == 1
    assert s.internal_hf == int(3.5 * 10**18)
    assert Web3 is not None and s.depositor == Web3.to_checksum_address(SAMPLE_DEPOSITOR)


def test_abi_has_update_risk_signatures():
    abi = load_abi()
    names = {e.get("name") for e in abi if e.get("type") == "function"}
    assert "updateRisk" in names
    assert "updateRiskBatch" in names
    assert "getRisk" in names
    assert "getRiskByDepositor" in names
    update = next(e for e in abi if e.get("name") == "updateRisk")
    types = [i["type"] for i in update["inputs"]]
    assert types == [
        "bytes32",
        "address",
        "uint256",
        "uint8",
        "uint256",
        "bool",
        "uint64",
    ]


def test_encode_update_risk_dry_run_with_mock_web3():
    web3 = pytest.importorskip("web3")
    from web3 import Web3

    # eth_abi encoding only — no network
    w3 = Web3()
    contract_addr = "0x" + ("11" * 20)
    keeper = RiskOracleKeeper(
        dry_run=True,
        contract_address=contract_addr,
        web3=w3,
        oracle=MagicMock(),  # unused
    )
    snaps = snapshot_from_zero_borrow(_zb_report())
    payload = keeper.encode_update_risk(snaps[0])
    assert payload["method"] == "updateRisk"
    assert payload["dry_run"] is True
    assert payload["data"].startswith("0x")
    assert len(payload["data"]) > 10
    assert payload["args"]["zone"] == 0
    assert payload["args"]["internal_hf"] == str(MAX_UINT256)

    batch = keeper.encode_update_risk_batch(snaps)
    assert batch["method"] == "updateRiskBatch"
    assert batch["count"] == 1
    assert batch["data"].startswith("0x")


def test_publish_dry_run_default_does_not_send(monkeypatch):
    web3 = pytest.importorskip("web3")
    from web3 import Web3

    monkeypatch.delenv("REAMPLIFY_KEEPER_LIVE", raising=False)
    w3 = Web3()
    keeper = RiskOracleKeeper(
        dry_run=True,
        contract_address="0x" + ("22" * 20),
        web3=w3,
        oracle=MagicMock(),
    )
    snaps = snapshot_from_zero_borrow(_zb_report())
    result = keeper.publish(snaps)
    assert result["status"] == "dry_run"
    assert "tx_hash" not in result


def test_publish_blocked_without_live_env(monkeypatch):
    web3 = pytest.importorskip("web3")
    from web3 import Web3

    monkeypatch.delenv("REAMPLIFY_KEEPER_LIVE", raising=False)
    w3 = Web3()
    keeper = RiskOracleKeeper(
        dry_run=False,
        contract_address="0x" + ("22" * 20),
        web3=w3,
        oracle=MagicMock(),
        private_key="0x" + ("ab" * 32),
    )
    snaps = snapshot_from_zero_borrow(_zb_report())
    result = keeper.publish(snaps)
    assert result["status"] == "blocked_live_flag"
