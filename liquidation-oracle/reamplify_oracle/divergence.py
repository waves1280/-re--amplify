"""Divergence Event monitoring — A.5.

*** BORROW-ENABLED ONLY (Board-authorized B.1.2) ***
Compares Internal HF vs Spoke on-chain HF — N/A under Zero-Borrow.

Flag if |Internal − Spoke| > tolerance for > persistence_days (default 5).
Divergence escalates to at least Red immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from reamplify_oracle.config import DivergenceConfig
from reamplify_oracle.models import EscalationZone, HealthFactorReport


@dataclass
class DivergenceTracker:
    """In-memory persistence tracker for divergence condition."""

    config: DivergenceConfig = field(default_factory=DivergenceConfig)
    _first_breach_at: dict[str, datetime] = field(default_factory=dict)

    def evaluate(self, report: HealthFactorReport) -> dict[str, Any] | None:
        if report.internal_hf is None or report.spoke_hf is None:
            # Clear tracker when we cannot compare
            self._first_breach_at.pop(report.depositor_address, None)
            report.notes.append(
                "Divergence check skipped: Spoke HF unavailable "
                "(stub provider or missing adapter). Indexer has no native HF field."
            )
            return None

        delta = abs(report.internal_hf - report.spoke_hf)
        report.divergence = delta
        now = datetime.now(timezone.utc)
        key = report.depositor_address

        if delta <= self.config.tolerance:
            self._first_breach_at.pop(key, None)
            report.divergence_alert = False
            return None

        first = self._first_breach_at.get(key)
        if first is None:
            self._first_breach_at[key] = now
            first = now

        elapsed = now - first
        persistent = elapsed > timedelta(days=self.config.persistence_days)

        # A.5: divergence escalates to at least Red immediately
        if report.zone in {EscalationZone.GREEN, EscalationZone.ZERO_BORROW, EscalationZone.UNKNOWN}:
            report.zone = EscalationZone.RED
            report.notes.append(
                "A.5 Divergence Event: zone escalated to at least RED immediately."
            )

        alert = {
            "type": "DIVERGENCE_EVENT",
            "policy": "A.5",
            "internal_hf": report.internal_hf,
            "spoke_hf": report.spoke_hf,
            "abs_delta": delta,
            "tolerance": self.config.tolerance,
            "breach_since": first.isoformat(),
            "persistent_over_days": persistent,
            "persistence_days_required": self.config.persistence_days,
            "required_actions": [
                "Treat as at least Red escalation immediately (A.5).",
                "Investigate oracle / adapter / indexer lag.",
                "Do not liquidate solely on Internal HF — confirm Spoke HF.",
            ],
        }
        report.divergence_alert = True
        report.alerts.append(alert)
        return alert
