from reamplify_oracle.config import DivergenceConfig, OperatingMode
from reamplify_oracle.divergence import DivergenceTracker
from reamplify_oracle.models import EscalationZone, HealthFactorReport


def test_divergence_escalates_to_red():
    tracker = DivergenceTracker(DivergenceConfig(tolerance=0.05, persistence_days=5))
    report = HealthFactorReport(
        depositor_address="0xabc",
        operating_mode=OperatingMode.BORROW_ENABLED.value,
        internal_hf=3.5,
        zone=EscalationZone.GREEN,
        total_collateral_btc=1.0,
        total_collateral_usd=100_000,
        collateral_factor=0.78,
        total_debt_usd=20_000,
        btc_reference=None,
        spoke_hf=3.0,  # delta 0.5 > 0.05
    )
    alert = tracker.evaluate(report)
    assert alert is not None
    assert report.zone == EscalationZone.RED
    assert report.divergence_alert is True


def test_no_spoke_skips():
    tracker = DivergenceTracker()
    report = HealthFactorReport(
        depositor_address="0xabc",
        operating_mode=OperatingMode.BORROW_ENABLED.value,
        internal_hf=2.0,
        zone=EscalationZone.RED,
        total_collateral_btc=1.0,
        total_collateral_usd=100_000,
        collateral_factor=0.78,
        total_debt_usd=30_000,
        btc_reference=None,
        spoke_hf=None,
    )
    assert tracker.evaluate(report) is None
