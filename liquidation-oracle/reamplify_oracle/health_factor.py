"""Internal Health Factor computation — A.3.2(c).

*** BORROW-ENABLED ONLY (Board-authorized B.1.2) ***
Not used for reAmplify Zero-Borrow / new vault monitoring.
Prefer CellVaultMonitor / evaluate_vault / evaluate_cell.

HF = (Total Collateral Value × Collateral Factor) ÷ Total Debt Value
Collateral: sats → BTC → USD via Reference Price
CF from reserve collateralFactor (bps/10000) or governance override
Debt: net borrow−repay valued in USD
Debt 0 → infinite HF / Zero-Borrow posture
Spoke liquidatable when Spoke HF < 1.0 (report threshold; Internal HF is monitoring only)
"""

from __future__ import annotations

from reamplify_oracle.config import EscalationConfig, OperatingMode
from reamplify_oracle.models import (
    SATOSHIS_PER_BTC,
    BtcReferencePrice,
    EscalationZone,
    HealthFactorReport,
    PositionState,
    ReserveInfo,
)


def resolve_collateral_factor(
    reserves: dict[str, ReserveInfo],
    *,
    vault_btc_reserve_id: str = "3",
    override_bps: int | None = None,
) -> float:
    if override_bps is not None:
        return override_bps / 10_000.0
    info = reserves.get(vault_btc_reserve_id)
    if info is None:
        # Fall back to any reserve with a non-zero CF (typically vaultBTC)
        for r in reserves.values():
            if r.collateral_factor_bps > 0:
                return r.collateral_factor_bps / 10_000.0
        return 0.0
    return info.collateral_factor_bps / 10_000.0


def compute_internal_hf(
    collateral_usd: float,
    collateral_factor: float,
    debt_usd: float,
) -> float | None:
    """Return HF or None for infinite (zero debt)."""
    if debt_usd <= 0:
        return None
    return (collateral_usd * collateral_factor) / debt_usd


def classify_zone(
    hf: float | None,
    mode: OperatingMode,
    escalation: EscalationConfig,
) -> EscalationZone:
    if mode == OperatingMode.ZERO_BORROW or hf is None:
        return EscalationZone.ZERO_BORROW
    if hf >= escalation.green_min:
        return EscalationZone.GREEN
    if hf >= escalation.red_min:
        return EscalationZone.RED
    return EscalationZone.CRITICAL


def build_hf_report(
    position: PositionState,
    *,
    mode: OperatingMode,
    collateral_factor: float,
    btc_ref: BtcReferencePrice,
    escalation: EscalationConfig,
    spoke_hf: float | None = None,
) -> HealthFactorReport:
    collateral_btc = position.total_collateral_sats / SATOSHIS_PER_BTC
    # Prefer sum of live collateral slices if present
    if position.collaterals:
        collateral_btc = sum(c.amount_sats for c in position.collaterals) / SATOSHIS_PER_BTC
    collateral_usd = collateral_btc * btc_ref.price_usd
    debt_usd = position.total_debt_usd

    notes: list[str] = [
        "Internal HF is monitoring only (A.3).",
        f"Spoke liquidatable threshold reported as HF < {escalation.spoke_liquidatable_threshold}.",
        "BTC Reference Price must NOT be used for Insurance Return calculations (A.3.4 / B.5).",
    ]

    if mode == OperatingMode.ZERO_BORROW:
        notes.append("Operating mode ZERO_BORROW (B.1): no debt monitoring for liquidation.")
        hf = None
        zone = EscalationZone.ZERO_BORROW
    else:
        hf = compute_internal_hf(collateral_usd, collateral_factor, debt_usd)
        zone = classify_zone(hf, mode, escalation)
        if hf is None:
            notes.append("Outstanding debt is 0 → infinite Internal HF / Zero-Borrow posture.")

    return HealthFactorReport(
        depositor_address=position.depositor_address,
        operating_mode=mode.value,
        internal_hf=hf,
        zone=zone,
        total_collateral_btc=collateral_btc,
        total_collateral_usd=collateral_usd,
        collateral_factor=collateral_factor,
        total_debt_usd=debt_usd,
        btc_reference=btc_ref,
        spoke_hf=spoke_hf,
        spoke_liquidatable_threshold=escalation.spoke_liquidatable_threshold,
        liquidatable_on_spoke_if_below=escalation.spoke_liquidatable_threshold,
        position=position,
        notes=notes,
    )
