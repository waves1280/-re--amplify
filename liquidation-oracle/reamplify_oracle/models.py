"""Domain models for vault/Cell monitoring, optional HF, alerts, and redemption.

Primary: Zero-Borrow vault lifecycle (A.2.1 / B.1.1).
Optional Borrow-Enabled: A.3 HF, A.4 zones, A.5 divergence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EscalationZone(str, Enum):
    """A.4 escalation zones (Borrow-Enabled only)."""

    GREEN = "GREEN"  # Internal HF ≥ 3.0
    RED = "RED"  # 1.5 ≤ Internal HF < 3.0
    CRITICAL = "CRITICAL"  # Internal HF < 1.5
    ZERO_BORROW = "ZERO_BORROW"  # No debt / Zero-Borrow posture
    UNKNOWN = "UNKNOWN"


class RedemptionPath(str, Enum):
    PATH_1_ORDINARY = "PATH_1_ORDINARY"
    PATH_2_LIQUIDATION = "PATH_2_LIQUIDATION"
    PATH_3_WOTS_SELF_CLAIM = "PATH_3_WOTS_SELF_CLAIM"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    NOTICE_SERVED = "NOTICE_SERVED"
    BOARD_NOTIFIED = "BOARD_NOTIFIED"
    POSTMORTEM_PENDING = "POSTMORTEM_PENDING"
    CLOSED = "CLOSED"
    REVERTED_ZERO_BORROW = "REVERTED_ZERO_BORROW"


SATOSHIS_PER_BTC = 100_000_000


@dataclass(frozen=True)
class ReserveInfo:
    reserve_id: str
    underlying: str
    decimals: int
    collateral_factor_bps: int
    symbol: str | None = None
    borrowable: bool = False


@dataclass
class CollateralSlice:
    vault_id: str
    amount_sats: int
    vault_status: str | None
    aave_vault_status: str | None
    liquidation_index: int = 0
    in_use: bool | None = None


@dataclass
class DebtByReserve:
    reserve_id: str
    net_raw: int  # borrow − repay in reserve decimals units
    decimals: int
    symbol: str | None
    usd_value: float


@dataclass
class IndexerFreshness:
    raw_status: dict[str, Any]
    chain_id: str | None = None
    block_number: int | None = None
    block_timestamp: int | None = None


@dataclass
class PositionState:
    depositor_address: str
    proxy_contract: str | None
    total_collateral_sats: int
    collaterals: list[CollateralSlice]
    debt_by_reserve: list[DebtByReserve]
    activity_summary: dict[str, int]
    has_liquidation_activity: bool
    liquidated_vault_ids: list[str]
    freshness: IndexerFreshness | None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_debt_usd(self) -> float:
        return sum(d.usd_value for d in self.debt_by_reserve)

    @property
    def is_zero_debt(self) -> bool:
        return self.total_debt_usd <= 0 and all(d.net_raw <= 0 for d in self.debt_by_reserve)


@dataclass
class BtcReferencePrice:
    price_usd: float
    sources: dict[str, float]
    aggregate_method: str
    baseline_usd: float
    decline_vs_baseline_pct: float
    recommend_suspend_new_policies: bool
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = "NOT for Insurance Return calculations (A.3.4 / B.5)"


@dataclass
class HealthFactorReport:
    """Internal HF per A.3.2(c). Monitoring only — Spoke liquidatable when Spoke HF < 1.0."""

    depositor_address: str
    operating_mode: str
    internal_hf: float | None  # None → infinite / zero-borrow
    zone: EscalationZone
    total_collateral_btc: float
    total_collateral_usd: float
    collateral_factor: float
    total_debt_usd: float
    btc_reference: BtcReferencePrice | None
    spoke_hf: float | None = None
    divergence: float | None = None
    divergence_alert: bool = False
    spoke_liquidatable_threshold: float = 1.0
    liquidatable_on_spoke_if_below: float = 1.0
    alerts: list[dict[str, Any]] = field(default_factory=list)
    position: PositionState | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "depositor_address": self.depositor_address,
            "operating_mode": self.operating_mode,
            "internal_hf": self.internal_hf if self.internal_hf is not None else "infinite",
            "zone": self.zone.value,
            "total_collateral_btc": self.total_collateral_btc,
            "total_collateral_usd": self.total_collateral_usd,
            "collateral_factor": self.collateral_factor,
            "total_debt_usd": self.total_debt_usd,
            "btc_reference_usd": self.btc_reference.price_usd if self.btc_reference else None,
            "btc_decline_vs_baseline_pct": (
                self.btc_reference.decline_vs_baseline_pct if self.btc_reference else None
            ),
            "recommend_suspend_new_policies": (
                self.btc_reference.recommend_suspend_new_policies if self.btc_reference else False
            ),
            "spoke_hf": self.spoke_hf,
            "divergence": self.divergence,
            "divergence_alert": self.divergence_alert,
            "spoke_liquidatable_threshold": self.spoke_liquidatable_threshold,
            "alerts": self.alerts,
            "notes": self.notes,
            "has_liquidation_activity": (
                self.position.has_liquidation_activity if self.position else False
            ),
            "liquidated_vault_ids": (
                self.position.liquidated_vault_ids if self.position else []
            ),
        }


@dataclass
class WotsCustodian:
    """Path 3 custodianship tracking — status only; no secrets."""

    name: str
    role: str
    artifact_label: str  # e.g. "WOTS_PK_SHARE_A" — never a secret
    status: str = "assigned"  # assigned | verified | revoked


@dataclass
class RedemptionIncident:
    incident_id: str
    path: RedemptionPath
    status: IncidentStatus
    depositor_address: str | None
    vault_ids: list[str]
    opened_at: datetime
    notice_days_required: int | None = None
    dual_signoff_board: bool = False
    dual_signoff_commission: bool = False
    claim_exceeds_premium_reserve: bool = False
    board_notified: bool = False
    commission_notified: bool = False
    postmortem_due_by: datetime | None = None
    auto_revert_zero_borrow: bool = False
    wots_custodians: list[WotsCustodian] = field(default_factory=list)
    timing_notes: dict[str, Any] = field(default_factory=dict)
    fairness_payment_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "path": self.path.value,
            "status": self.status.value,
            "depositor_address": self.depositor_address,
            "vault_ids": self.vault_ids,
            "opened_at": self.opened_at.isoformat(),
            "notice_days_required": self.notice_days_required,
            "dual_signoff_board": self.dual_signoff_board,
            "dual_signoff_commission": self.dual_signoff_commission,
            "claim_exceeds_premium_reserve": self.claim_exceeds_premium_reserve,
            "board_notified": self.board_notified,
            "commission_notified": self.commission_notified,
            "postmortem_due_by": self.postmortem_due_by.isoformat()
            if self.postmortem_due_by
            else None,
            "auto_revert_zero_borrow": self.auto_revert_zero_borrow,
            "wots_custodians": [
                {"name": c.name, "role": c.role, "artifact_label": c.artifact_label, "status": c.status}
                for c in self.wots_custodians
            ],
            "timing_notes": self.timing_notes,
            "fairness_payment_notes": self.fairness_payment_notes,
            "metadata": self.metadata,
        }
