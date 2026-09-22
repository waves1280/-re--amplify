"""Insurance Returns oracle scaffolding — A.3.2.

Accepts monthly premiums/claims/reserves.
Figures marked pending_actuarial_confirmation until External Actuary flag set.
Explicitly separate from BTC Reference Price and Internal HF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MonthlyInsuranceFigures:
    period: str  # e.g. "2026-08"
    premiums_collected: float
    claims_paid: float
    reserves: float
    currency: str = "USD"
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pending_actuarial_confirmation: bool = True
    external_actuary_confirmed: bool = False
    notes: list[str] = field(default_factory=list)

    def confirm_by_external_actuary(self) -> None:
        self.external_actuary_confirmed = True
        self.pending_actuarial_confirmation = False
        self.notes.append(
            f"External Actuary confirmation recorded at {datetime.now(timezone.utc).isoformat()}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "premiums_collected": self.premiums_collected,
            "claims_paid": self.claims_paid,
            "reserves": self.reserves,
            "currency": self.currency,
            "submitted_at": self.submitted_at.isoformat(),
            "pending_actuarial_confirmation": self.pending_actuarial_confirmation,
            "external_actuary_confirmed": self.external_actuary_confirmed,
            "notes": self.notes,
            "separation_notice": (
                "Insurance Returns are independent of BTC Reference Price (A.3.4) "
                "and Internal HF (A.3.2(c)). Never mix feeds."
            ),
        }


class InsuranceReturnsOracle:
    """Scaffolding only — does not compute returns from BTC price or HF."""

    def __init__(self) -> None:
        self._figures: dict[str, MonthlyInsuranceFigures] = {}

    def submit_monthly(
        self,
        period: str,
        premiums_collected: float,
        claims_paid: float,
        reserves: float,
        *,
        currency: str = "USD",
    ) -> MonthlyInsuranceFigures:
        fig = MonthlyInsuranceFigures(
            period=period,
            premiums_collected=premiums_collected,
            claims_paid=claims_paid,
            reserves=reserves,
            currency=currency,
            pending_actuarial_confirmation=True,
            external_actuary_confirmed=False,
            notes=[
                "Marked pending_actuarial_confirmation until External Actuary flag set (A.3.2).",
            ],
        )
        self._figures[period] = fig
        return fig

    def confirm(self, period: str) -> MonthlyInsuranceFigures:
        fig = self._figures[period]
        fig.confirm_by_external_actuary()
        return fig

    def get(self, period: str) -> MonthlyInsuranceFigures | None:
        return self._figures.get(period)

    def all(self) -> list[MonthlyInsuranceFigures]:
        return list(self._figures.values())
