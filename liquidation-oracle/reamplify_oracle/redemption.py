"""Liquidation & Redemption Rules — Part B.

Primary for reAmplify Zero-Borrow: Path 1 (claim-driven).
Path 2 only if Borrow-Enabled OR unexpected liquidated status on indexer.

Path 1 — ordinary / claim-driven: ≥30 days notice; dual-signoff; claim-exceeds-premium-reserve
Path 2 — liquidation-triggered (Borrow-Enabled): same-day Board+Commission; post-mortem ≤5 BD;
         auto-revert to Zero-Borrow
Path 3 — depositor WOTS self-claim: multi-person custodians (no secrets in code)
Timing: CSA Support Notice (2 BD) vs TBV challenge (~3d) vs peg-in refund (~14d)
B.6: liquidation bonus charged to Cell; fairness as WBTC with BTC haircut until converted
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from reamplify_oracle.config import OperatingMode, TimingConstants
from reamplify_oracle.models import (
    IncidentStatus,
    PositionState,
    RedemptionIncident,
    RedemptionPath,
    WotsCustodian,
)

logger = logging.getLogger(__name__)


def _add_business_days(start: datetime, days: int) -> datetime:
    """Add N business days (Mon–Fri); ignores holidays."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


class RedemptionEngine:
    def __init__(
        self,
        timing: TimingConstants | None = None,
        *,
        mode: OperatingMode = OperatingMode.ZERO_BORROW,
    ) -> None:
        self.timing = timing or TimingConstants()
        self.mode = mode
        self.incidents: list[RedemptionIncident] = []

    def timing_constants_view(self) -> dict[str, Any]:
        return {
            "csa_support_notice_business_days": self.timing.csa_support_notice_business_days,
            "tbv_challenge_approx_days": self.timing.tbv_challenge_approx_days,
            "pegin_refund_timelock_calendar_days": self.timing.pegin_refund_timelock_calendar_days,
            "path1_notice_calendar_days": self.timing.path1_notice_calendar_days,
            "path2_postmortem_business_days": self.timing.path2_postmortem_business_days,
            "note": (
                "CSA Support Notice (2 BD) vs TBV challenge (~3 days) vs "
                "peg-in refund timelock (~14 days) as documented timing constants."
            ),
        }

    def open_path1_notice(
        self,
        *,
        depositor_address: str | None = None,
        vault_ids: list[str] | None = None,
        claim_exceeds_premium_reserve: bool = False,
        dual_signoff_board: bool = False,
        dual_signoff_commission: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> RedemptionIncident:
        """Path 1 — ordinary / claim-driven redemption notice (≥30 days)."""
        now = datetime.now(timezone.utc)
        incident = RedemptionIncident(
            incident_id=f"P1-{uuid.uuid4().hex[:10]}",
            path=RedemptionPath.PATH_1_ORDINARY,
            status=IncidentStatus.NOTICE_SERVED,
            depositor_address=depositor_address.lower() if depositor_address else None,
            vault_ids=vault_ids or [],
            opened_at=now,
            notice_days_required=self.timing.path1_notice_calendar_days,
            dual_signoff_board=dual_signoff_board,
            dual_signoff_commission=dual_signoff_commission,
            claim_exceeds_premium_reserve=claim_exceeds_premium_reserve,
            timing_notes=self.timing_constants_view(),
            metadata=metadata or {},
        )
        if claim_exceeds_premium_reserve:
            incident.metadata["trigger"] = "claim_exceeds_premium_reserve"
        logger.info(
            "Opened Path 1 notice %s (≥%s calendar days)",
            incident.incident_id,
            self.timing.path1_notice_calendar_days,
        )
        self.incidents.append(incident)
        return incident

    def set_path1_dual_signoff(
        self,
        incident_id: str,
        *,
        board: bool | None = None,
        commission: bool | None = None,
    ) -> RedemptionIncident:
        incident = self._get(incident_id)
        if incident.path != RedemptionPath.PATH_1_ORDINARY:
            raise ValueError("Dual-signoff flags apply to Path 1")
        if board is not None:
            incident.dual_signoff_board = board
        if commission is not None:
            incident.dual_signoff_commission = commission
        return incident

    def open_path2_liquidation_incident(
        self,
        *,
        depositor_address: str | None = None,
        vault_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> RedemptionIncident:
        """Path 2 — liquidation-triggered (Borrow-Enabled only unless force=True)."""
        if self.mode != OperatingMode.BORROW_ENABLED and not force:
            raise RuntimeError(
                "Path 2 liquidation workflow requires BORROW_ENABLED mode (B.1). "
                "Pass force=True only for tabletop drills."
            )
        now = datetime.now(timezone.utc)
        postmortem_due = _add_business_days(now, self.timing.path2_postmortem_business_days)
        fairness_notes = [
            "B.6 Liquidation bonus: charge bonus to Cell.",
            "B.6 Fairness payment: settle as WBTC with BTC haircut until converted.",
        ]
        incident = RedemptionIncident(
            incident_id=f"P2-{uuid.uuid4().hex[:10]}",
            path=RedemptionPath.PATH_2_LIQUIDATION,
            status=IncidentStatus.BOARD_NOTIFIED,
            depositor_address=depositor_address.lower() if depositor_address else None,
            vault_ids=vault_ids or [],
            opened_at=now,
            board_notified=True,
            commission_notified=True,
            postmortem_due_by=postmortem_due,
            auto_revert_zero_borrow=True,
            timing_notes=self.timing_constants_view(),
            fairness_payment_notes=fairness_notes,
            metadata={
                **(metadata or {}),
                "same_day_notify": True,
                "workflow": "Path 2 liquidation-triggered",
            },
        )
        # Auto-revert programme posture
        self.mode = OperatingMode.ZERO_BORROW
        incident.status = IncidentStatus.REVERTED_ZERO_BORROW
        logger.warning(
            "Path 2 incident %s opened; programme auto-reverted to ZERO_BORROW; "
            "post-mortem due %s",
            incident.incident_id,
            postmortem_due.isoformat(),
        )
        self.incidents.append(incident)
        return incident

    def open_path3_wots_self_claim(
        self,
        *,
        depositor_address: str,
        vault_ids: list[str] | None = None,
        custodians: list[WotsCustodian] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RedemptionIncident:
        """Path 3 — track WOTS artifact custodians only (no crypto secrets)."""
        custodians = custodians or []
        self._assert_no_custodian_concentration(custodians)
        now = datetime.now(timezone.utc)
        incident = RedemptionIncident(
            incident_id=f"P3-{uuid.uuid4().hex[:10]}",
            path=RedemptionPath.PATH_3_WOTS_SELF_CLAIM,
            status=IncidentStatus.OPEN,
            depositor_address=depositor_address.lower(),
            vault_ids=vault_ids or [],
            opened_at=now,
            wots_custodians=list(custodians),
            timing_notes=self.timing_constants_view(),
            metadata={
                **(metadata or {}),
                "secrets_policy": "No WOTS secrets or private keys stored in this system.",
            },
        )
        self.incidents.append(incident)
        return incident

    def update_wots_custodian_status(
        self, incident_id: str, artifact_label: str, status: str
    ) -> RedemptionIncident:
        incident = self._get(incident_id)
        for c in incident.wots_custodians:
            if c.artifact_label == artifact_label:
                c.status = status
                break
        else:
            raise KeyError(f"No custodian with artifact_label={artifact_label!r}")
        return incident

    def maybe_trigger_path2_from_position(
        self, position: PositionState
    ) -> RedemptionIncident | None:
        """On indexer liquidation activity or vault status liquidated → Path 2."""
        if not position.has_liquidation_activity and not position.liquidated_vault_ids:
            return None
        return self.open_path2_liquidation_incident(
            depositor_address=position.depositor_address,
            vault_ids=position.liquidated_vault_ids,
            metadata={
                "source": "indexer",
                "activity_summary": position.activity_summary,
                "trigger": "type:liquidation or vault status:liquidated",
            },
            force=(self.mode != OperatingMode.BORROW_ENABLED),
        )

    def _assert_no_custodian_concentration(self, custodians: list[WotsCustodian]) -> None:
        if not custodians:
            return
        if len(custodians) < 2:
            raise ValueError(
                "Path 3 requires multi-person custodianship — no single concentration (Part B)."
            )
        by_person: dict[str, int] = {}
        for c in custodians:
            by_person[c.name] = by_person.get(c.name, 0) + 1
        total = len(custodians)
        for name, count in by_person.items():
            if count == total:
                raise ValueError(
                    f"Custodian concentration detected for {name!r}: holds all artifacts"
                )

    def _get(self, incident_id: str) -> RedemptionIncident:
        for inc in self.incidents:
            if inc.incident_id == incident_id:
                return inc
        raise KeyError(incident_id)
