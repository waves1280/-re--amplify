"""Escalation zones and structured alerts — A.4.

*** BORROW-ENABLED ONLY (Board-authorized B.1.2) ***
Green / Red / Critical HF zones do NOT apply under Zero-Borrow (B.1.1).
Zero-Borrow uses CellVaultMonitor lifecycle alerts instead.

Green: HF ≥ 3.0
Red: 1.5 ≤ HF < 3.0
Critical: HF < 1.5
"""

from __future__ import annotations

from typing import Any

from reamplify_oracle.models import EscalationZone, HealthFactorReport


ZONE_ACTIONS: dict[EscalationZone, list[str]] = {
    EscalationZone.GREEN: [
        "Continue routine Internal HF monitoring.",
        "No Board escalation required.",
    ],
    EscalationZone.RED: [
        "Notify Risk / Board watchlist within policy SLA.",
        "Increase monitoring frequency.",
        "Prepare contingency: Path 2 liquidation workflow if Spoke approaches HF < 1.0.",
        "Review collateral and outstanding debt by reserve.",
    ],
    EscalationZone.CRITICAL: [
        "Immediate Board + Commission escalation.",
        "Stand up liquidation incident readiness (Path 2).",
        "Confirm Spoke HF via on-chain adapter; do not rely on Internal HF alone for liquidation.",
        "Halt new Borrow-Enabled exposure for this Cell pending review.",
    ],
    EscalationZone.ZERO_BORROW: [
        "Zero-Borrow posture: track vaults/valuation hooks only; no debt liquidation monitoring.",
    ],
    EscalationZone.UNKNOWN: [
        "Unable to classify zone — verify indexer freshness and price feeds.",
    ],
}


def emit_zone_alerts(report: HealthFactorReport) -> list[dict[str, Any]]:
    actions = ZONE_ACTIONS.get(report.zone, ZONE_ACTIONS[EscalationZone.UNKNOWN])
    alert: dict[str, Any] = {
        "type": "ESCALATION_ZONE",
        "policy": "A.4",
        "zone": report.zone.value,
        "internal_hf": report.internal_hf if report.internal_hf is not None else "infinite",
        "depositor": report.depositor_address,
        "required_actions": actions,
    }
    alerts = [alert]

    if report.btc_reference and report.btc_reference.recommend_suspend_new_policies:
        alerts.append(
            {
                "type": "BTC_REFERENCE_CRASH",
                "policy": "B.5",
                "decline_vs_baseline_pct": report.btc_reference.decline_vs_baseline_pct,
                "baseline_usd": report.btc_reference.baseline_usd,
                "spot_usd": report.btc_reference.price_usd,
                "required_actions": [
                    "Recommend suspend writing new policies until Board review (B.5).",
                    "Do NOT use Reference Price for Insurance Return calculations.",
                ],
            }
        )

    if report.position and report.position.has_liquidation_activity:
        alerts.append(
            {
                "type": "LIQUIDATION_ACTIVITY_DETECTED",
                "policy": "B Path 2",
                "vault_ids": report.position.liquidated_vault_ids,
                "required_actions": [
                    "Open Path 2 liquidation-triggered incident.",
                    "Same-day Board + Commission notify.",
                    "Post-mortem within 5 business days.",
                    "Auto-revert vault programme to Zero-Borrow.",
                ],
            }
        )

    report.alerts.extend(alerts)
    return alerts
