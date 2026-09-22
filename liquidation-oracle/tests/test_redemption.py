import pytest

from reamplify_oracle.config import OperatingMode
from reamplify_oracle.models import WotsCustodian
from reamplify_oracle.redemption import RedemptionEngine


def test_path1_notice():
    eng = RedemptionEngine(mode=OperatingMode.ZERO_BORROW)
    inc = eng.open_path1_notice(
        depositor_address="0xAbC",
        claim_exceeds_premium_reserve=True,
        dual_signoff_board=True,
    )
    assert inc.notice_days_required == 30
    assert inc.claim_exceeds_premium_reserve
    assert inc.depositor_address == "0xabc"
    eng.set_path1_dual_signoff(inc.incident_id, commission=True)
    assert eng.incidents[0].dual_signoff_commission is True


def test_path2_requires_borrow_enabled():
    eng = RedemptionEngine(mode=OperatingMode.ZERO_BORROW)
    with pytest.raises(RuntimeError):
        eng.open_path2_liquidation_incident(depositor_address="0xabc")


def test_path2_auto_revert():
    eng = RedemptionEngine(mode=OperatingMode.BORROW_ENABLED)
    inc = eng.open_path2_liquidation_incident(
        depositor_address="0xabc", vault_ids=["0xvault"]
    )
    assert eng.mode == OperatingMode.ZERO_BORROW
    assert inc.auto_revert_zero_borrow
    assert inc.board_notified and inc.commission_notified
    assert inc.postmortem_due_by is not None
    assert any("Cell" in n for n in inc.fairness_payment_notes)


def test_path3_multi_custodian():
    eng = RedemptionEngine()
    with pytest.raises(ValueError):
        eng.open_path3_wots_self_claim(
            depositor_address="0xabc",
            custodians=[WotsCustodian("Only", "Board", "SHARE_A")],
        )
    inc = eng.open_path3_wots_self_claim(
        depositor_address="0xabc",
        custodians=[
            WotsCustodian("Alice", "Board", "SHARE_A"),
            WotsCustodian("Bob", "Commission", "SHARE_B"),
        ],
    )
    eng.update_wots_custodian_status(inc.incident_id, "SHARE_A", "verified")
    assert inc.wots_custodians[0].status == "verified"
