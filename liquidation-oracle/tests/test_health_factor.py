from reamplify_oracle.config import EscalationConfig, OperatingMode
from reamplify_oracle.health_factor import classify_zone, compute_internal_hf, resolve_collateral_factor
from reamplify_oracle.models import EscalationZone, ReserveInfo


def test_hf_formula():
    # Collateral 100k USD, CF 78%, debt 39k → HF = 2.0
    hf = compute_internal_hf(100_000, 0.78, 39_000)
    assert hf is not None
    assert abs(hf - 2.0) < 1e-9


def test_zero_debt_infinite():
    assert compute_internal_hf(50_000, 0.78, 0) is None


def test_zones():
    esc = EscalationConfig()
    assert classify_zone(3.0, OperatingMode.BORROW_ENABLED, esc) == EscalationZone.GREEN
    assert classify_zone(2.0, OperatingMode.BORROW_ENABLED, esc) == EscalationZone.RED
    assert classify_zone(1.2, OperatingMode.BORROW_ENABLED, esc) == EscalationZone.CRITICAL
    assert classify_zone(None, OperatingMode.BORROW_ENABLED, esc) == EscalationZone.ZERO_BORROW
    assert classify_zone(1.2, OperatingMode.ZERO_BORROW, esc) == EscalationZone.ZERO_BORROW


def test_cf_from_reserve_bps():
    reserves = {
        "3": ReserveInfo("3", "0xabc", 8, 7800, "vaultBTC"),
    }
    assert resolve_collateral_factor(reserves) == 0.78
    assert resolve_collateral_factor(reserves, override_bps=8000) == 0.8
