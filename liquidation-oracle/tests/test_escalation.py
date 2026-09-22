from datetime import datetime, timezone

from reamplify_oracle.config import OperatingMode
from reamplify_oracle.escalation import emit_zone_alerts
from reamplify_oracle.models import BtcReferencePrice, EscalationZone, HealthFactorReport


def _report(zone: EscalationZone, hf: float | None = 2.0) -> HealthFactorReport:
    btc = BtcReferencePrice(
        price_usd=90_000,
        sources={"coingecko": 90_000, "coinbase": 90_100},
        aggregate_method="median",
        baseline_usd=100_000,
        decline_vs_baseline_pct=10.0,
        recommend_suspend_new_policies=False,
        as_of=datetime.now(timezone.utc),
    )
    return HealthFactorReport(
        depositor_address="0xabc",
        operating_mode=OperatingMode.BORROW_ENABLED.value,
        internal_hf=hf,
        zone=zone,
        total_collateral_btc=1.0,
        total_collateral_usd=90_000,
        collateral_factor=0.78,
        total_debt_usd=30_000,
        btc_reference=btc,
    )


def test_red_zone_actions():
    r = _report(EscalationZone.RED)
    alerts = emit_zone_alerts(r)
    assert alerts[0]["zone"] == "RED"
    assert any("Board" in a or "monitoring" in a.lower() for a in alerts[0]["required_actions"])


def test_btc_crash_alert():
    r = _report(EscalationZone.GREEN)
    assert r.btc_reference is not None
    r.btc_reference.recommend_suspend_new_policies = True
    r.btc_reference.decline_vs_baseline_pct = 55.0
    alerts = emit_zone_alerts(r)
    types = [a["type"] for a in alerts]
    assert "BTC_REFERENCE_CRASH" in types
