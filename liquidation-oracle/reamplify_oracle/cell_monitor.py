"""Cell / vault programme monitoring for Zero-Borrow (A.2.1 / B.1.1).

Primary path for reAmplify's new vault — NO borrowing, NO on-chain liquidation risk.
Tracks vault lifecycle, activities (deposit/redeem/liquidation/claim_expired),
provider/fees/ackCount/expiration — without requiring aavePosition.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from reamplify_oracle.config import OperatingMode, OracleConfig
from reamplify_oracle.indexer_client import IndexerClient
from reamplify_oracle.models import (
    SATOSHIS_PER_BTC,
    BtcReferencePrice,
    EscalationZone,
    IndexerFreshness,
)
from reamplify_oracle.price_oracle import BtcReferencePriceOracle

logger = logging.getLogger(__name__)

# Lifecycle activities relevant in Zero-Borrow (NOT borrow/repay)
ZERO_BORROW_ACTIVITY_TYPES = frozenset(
    {"deposit", "withdrawal", "redeem", "liquidation", "claim_expired", "add_collateral", "remove_collateral"}
)

TERMINAL_STATUSES = frozenset({"redeemed", "liquidated", "expired", "invalid", "depositor_withdrawn"})
HEALTHY_STATUSES = frozenset({"available", "verified", "signatures_collected"})


@dataclass
class CellProgrammeConfig:
    """reAmplify Cell programme registration (new vault, Zero-Borrow default)."""

    cell_id: str
    name: str
    mode: OperatingMode = OperatingMode.ZERO_BORROW
    depositor_address: str | None = None
    vault_ids: list[str] = field(default_factory=list)
    board_btc_baseline_usd: float | None = None
    path1_notice_calendar_days: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "name": self.name,
            "mode": self.mode.value,
            "depositor_address": self.depositor_address,
            "vault_ids": list(self.vault_ids),
            "board_btc_baseline_usd": self.board_btc_baseline_usd,
            "path1_notice_calendar_days": self.path1_notice_calendar_days,
            "notes": list(self.notes),
        }


@dataclass
class VaultLifecycleSnapshot:
    vault_id: str
    status: str | None
    amount_sats: int
    amount_btc: float
    amount_usd: float | None
    depositor: str | None
    vault_provider: str | None
    vault_provider_name: str | None
    vault_provider_commission_bps: int | None
    ack_count: int | None
    in_use: bool | None
    application_entry_point: str | None
    pending_at: int | None
    verified_at: int | None
    activated_at: int | None
    expired_at: int | None
    expiration_reason: str | None
    claim_expired_until: int | None
    pegin_tx_hash: str | None
    fee_escrow: dict[str, Any] | None
    activity_summary: dict[str, int]
    recent_activities: list[dict[str, Any]]
    lifecycle_alerts: list[dict[str, Any]]
    is_liquidated: bool
    is_terminal: bool
    posture: str = "ZERO_BORROW"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ZeroBorrowReport:
    """Primary Zero-Borrow monitoring report (A.2.1 / B.1.1)."""

    scope: str  # "vault" | "cell"
    cell: CellProgrammeConfig | None
    operating_mode: str
    zone: EscalationZone
    on_chain_liquidation_risk: bool  # always False in Zero-Borrow
    internal_hf_applicable: bool  # False unless BORROW_ENABLED
    vaults: list[VaultLifecycleSnapshot]
    btc_reference: BtcReferencePrice | None
    freshness: IndexerFreshness | None
    alerts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "cell": self.cell.to_dict() if self.cell else None,
            "operating_mode": self.operating_mode,
            "zone": self.zone.value,
            "on_chain_liquidation_risk": self.on_chain_liquidation_risk,
            "internal_hf_applicable": self.internal_hf_applicable,
            "vaults": [v.to_dict() for v in self.vaults],
            "btc_reference_usd": self.btc_reference.price_usd if self.btc_reference else None,
            "btc_decline_vs_baseline_pct": (
                self.btc_reference.decline_vs_baseline_pct if self.btc_reference else None
            ),
            "recommend_suspend_new_policies": (
                self.btc_reference.recommend_suspend_new_policies if self.btc_reference else False
            ),
            "freshness": {
                "chain_id": self.freshness.chain_id if self.freshness else None,
                "block_number": self.freshness.block_number if self.freshness else None,
            },
            "alerts": self.alerts,
            "notes": self.notes,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class CellVaultMonitor:
    """Zero-Borrow Cell / vault monitor — does not require aavePosition."""

    def __init__(
        self,
        config: OracleConfig,
        indexer: IndexerClient,
        price_oracle: BtcReferencePriceOracle,
    ) -> None:
        self.config = config
        self.indexer = indexer
        self.price_oracle = price_oracle
        self.programmes: dict[str, CellProgrammeConfig] = {}

    def register_cell(self, programme: CellProgrammeConfig) -> CellProgrammeConfig:
        if programme.mode != OperatingMode.ZERO_BORROW:
            programme.notes.append(
                "WARNING: Non-Zero-Borrow mode requires Board authorization (B.1.2). "
                "reAmplify new vault default is ZERO_BORROW."
            )
        if programme.board_btc_baseline_usd is not None:
            self.config.btc_reference.baseline_usd = programme.board_btc_baseline_usd
        if programme.path1_notice_calendar_days is not None:
            self.config.timing.path1_notice_calendar_days = programme.path1_notice_calendar_days
        self.programmes[programme.cell_id] = programme
        logger.info(
            "Registered Cell programme %s (%s) mode=%s vaults=%s",
            programme.cell_id,
            programme.name,
            programme.mode.value,
            len(programme.vault_ids),
        )
        return programme

    def evaluate_vault(
        self,
        vault_id: str,
        *,
        cell: CellProgrammeConfig | None = None,
        btc_ref: BtcReferencePrice | None = None,
    ) -> ZeroBorrowReport:
        btc_ref = btc_ref or self.price_oracle.fetch()
        freshness = self.indexer.get_meta()
        snap = self._snapshot_vault(vault_id, btc_ref)
        return self._build_report(
            scope="vault",
            cell=cell,
            vaults=[snap],
            btc_ref=btc_ref,
            freshness=freshness,
        )

    def evaluate_cell(
        self,
        cell: CellProgrammeConfig | str,
        *,
        btc_ref: BtcReferencePrice | None = None,
    ) -> ZeroBorrowReport:
        if isinstance(cell, str):
            cell = self.programmes[cell]
        btc_ref = btc_ref or self.price_oracle.fetch()
        freshness = self.indexer.get_meta()

        vault_ids = list(cell.vault_ids)
        if cell.depositor_address and not vault_ids:
            listed = self.indexer.get_vaults_for_depositor(cell.depositor_address)
            vault_ids = [v["id"] for v in listed]

        snaps = [self._snapshot_vault(vid, btc_ref) for vid in vault_ids]
        return self._build_report(
            scope="cell",
            cell=cell,
            vaults=snaps,
            btc_ref=btc_ref,
            freshness=freshness,
        )

    def _snapshot_vault(self, vault_id: str, btc_ref: BtcReferencePrice) -> VaultLifecycleSnapshot:
        raw = self.indexer.get_vault(vault_id)
        if not raw:
            return VaultLifecycleSnapshot(
                vault_id=vault_id,
                status=None,
                amount_sats=0,
                amount_btc=0.0,
                amount_usd=0.0,
                depositor=None,
                vault_provider=None,
                vault_provider_name=None,
                vault_provider_commission_bps=None,
                ack_count=None,
                in_use=None,
                application_entry_point=None,
                pending_at=None,
                verified_at=None,
                activated_at=None,
                expired_at=None,
                expiration_reason=None,
                claim_expired_until=None,
                pegin_tx_hash=None,
                fee_escrow=None,
                activity_summary={},
                recent_activities=[],
                lifecycle_alerts=[
                    {
                        "type": "VAULT_NOT_FOUND",
                        "policy": "A.2.1",
                        "vault_id": vault_id,
                        "required_actions": ["Verify vault_id / indexer sync."],
                    }
                ],
                is_liquidated=False,
                is_terminal=False,
            )

        amount_sats = int(str(raw.get("amount") or 0))
        amount_btc = amount_sats / SATOSHIS_PER_BTC
        provider_id = raw.get("vaultProvider")
        provider_name = None
        if provider_id:
            prov = self.indexer.get_vault_provider(provider_id)
            if prov:
                provider_name = prov.get("name")

        fee_escrow = self.indexer.get_vault_fee_escrow(vault_id)

        activities = list(
            self.indexer.iter_vault_activities(vault_id=vault_id, page_size=200)
        )
        summary: dict[str, int] = {}
        recent: list[dict[str, Any]] = []
        for act in activities:
            atype = act.get("type") or ""
            summary[atype] = summary.get(atype, 0) + 1
            if atype in ZERO_BORROW_ACTIVITY_TYPES or True:
                recent.append(
                    {
                        "type": atype,
                        "amount": act.get("amount"),
                        "timestamp": act.get("timestamp"),
                        "depositor": act.get("depositor"),
                    }
                )
        # Keep last 10 chronologically (iterator is asc)
        recent = recent[-10:]

        status = raw.get("status")
        alerts = self._lifecycle_alerts(raw, summary)

        return VaultLifecycleSnapshot(
            vault_id=vault_id,
            status=status,
            amount_sats=amount_sats,
            amount_btc=amount_btc,
            amount_usd=amount_btc * btc_ref.price_usd,
            depositor=raw.get("depositor"),
            vault_provider=provider_id,
            vault_provider_name=provider_name,
            vault_provider_commission_bps=_as_optional_int(raw.get("vaultProviderCommissionBps")),
            ack_count=_as_optional_int(raw.get("ackCount")),
            in_use=raw.get("inUse"),
            application_entry_point=raw.get("applicationEntryPoint"),
            pending_at=_as_optional_int(raw.get("pendingAt")),
            verified_at=_as_optional_int(raw.get("verifiedAt")),
            activated_at=_as_optional_int(raw.get("activatedAt")),
            expired_at=_as_optional_int(raw.get("expiredAt")),
            expiration_reason=raw.get("expirationReason"),
            claim_expired_until=_as_optional_int(raw.get("claimExpiredUntil")),
            pegin_tx_hash=raw.get("peginTxHash"),
            fee_escrow=fee_escrow,
            activity_summary=summary,
            recent_activities=recent,
            lifecycle_alerts=alerts,
            is_liquidated=(status == "liquidated") or summary.get("liquidation", 0) > 0,
            is_terminal=status in TERMINAL_STATUSES if status else False,
        )

    def _lifecycle_alerts(
        self, raw: dict[str, Any], summary: dict[str, int]
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        status = raw.get("status")
        if status == "liquidated" or summary.get("liquidation", 0) > 0:
            alerts.append(
                {
                    "type": "UNEXPECTED_LIQUIDATION",
                    "policy": "B Path 2 / B.1.1",
                    "vault_id": raw.get("id"),
                    "note": (
                        "Liquidation is unexpected under Zero-Borrow. "
                        "Open Path 2 incident and escalate to Board."
                    ),
                    "required_actions": [
                        "Open Path 2 liquidation incident (even if rare in Zero-Borrow).",
                        "Same-day Board + Commission notify.",
                        "Investigate indexer / protocol anomaly.",
                    ],
                }
            )
        if status == "expired" or raw.get("expiredAt"):
            alerts.append(
                {
                    "type": "PEGSIN_EXPIRATION_RISK",
                    "policy": "A.2.1",
                    "vault_id": raw.get("id"),
                    "expiration_reason": raw.get("expirationReason"),
                    "claim_expired_until": raw.get("claimExpiredUntil"),
                    "required_actions": [
                        "Monitor claim_expired window (~peg-in refund timelock).",
                        "Coordinate CSA Support Notice timing (2 BD) vs TBV challenge (~3d).",
                    ],
                }
            )
        if status == "pending":
            ack = _as_optional_int(raw.get("ackCount")) or 0
            alerts.append(
                {
                    "type": "PEGIN_PENDING",
                    "policy": "A.2.1",
                    "vault_id": raw.get("id"),
                    "ack_count": ack,
                    "required_actions": [
                        "Track ackCount / signature collection until verified/available.",
                    ],
                }
            )
        return alerts

    def _build_report(
        self,
        *,
        scope: str,
        cell: CellProgrammeConfig | None,
        vaults: list[VaultLifecycleSnapshot],
        btc_ref: BtcReferencePrice,
        freshness: IndexerFreshness,
    ) -> ZeroBorrowReport:
        mode = cell.mode if cell else self.config.mode
        alerts: list[dict[str, Any]] = []
        for v in vaults:
            alerts.extend(v.lifecycle_alerts)

        if btc_ref.recommend_suspend_new_policies:
            alerts.append(
                {
                    "type": "BTC_REFERENCE_CRASH",
                    "policy": "B.5",
                    "decline_vs_baseline_pct": btc_ref.decline_vs_baseline_pct,
                    "baseline_usd": btc_ref.baseline_usd,
                    "spot_usd": btc_ref.price_usd,
                    "required_actions": [
                        "Recommend suspend writing new policies until Board review (B.5).",
                        "Do NOT use Reference Price for Insurance Return calculations.",
                    ],
                }
            )

        unexpected_liq = any(v.is_liquidated for v in vaults)
        # Zero-Borrow zone classification
        if mode == OperatingMode.ZERO_BORROW:
            zone = EscalationZone.ZERO_BORROW
            if any(v.status is None for v in vaults):
                zone = EscalationZone.UNKNOWN
            notes = [
                "Zero-Borrow posture (B.1 / A.2.1): no on-chain liquidation risk from borrowing.",
                "Internal HF monitoring is N/A unless Board authorizes BORROW_ENABLED (B.1.2).",
                "Primary signals: vault lifecycle status, deposit/redeem/claim_expired activities, "
                "provider/fees/ackCount/expiration.",
                "reAmplify new vault — Babylon indexer vault entities only; no Aave required.",
            ]
            on_chain_risk = False
            hf_applicable = False
        else:
            zone = EscalationZone.UNKNOWN
            notes = [
                "Cell configured for BORROW_ENABLED — use LiquidationOracle.evaluate_depositor_borrow_enabled().",
            ]
            on_chain_risk = True
            hf_applicable = True

        if unexpected_liq and mode == OperatingMode.ZERO_BORROW:
            notes.append(
                "Unexpected liquidation observed under Zero-Borrow — treat as Path 2 incident."
            )

        return ZeroBorrowReport(
            scope=scope,
            cell=cell,
            operating_mode=mode.value,
            zone=zone,
            on_chain_liquidation_risk=on_chain_risk,
            internal_hf_applicable=hf_applicable,
            vaults=vaults,
            btc_reference=btc_ref,
            freshness=freshness,
            alerts=alerts,
            notes=notes,
        )


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(str(value))
