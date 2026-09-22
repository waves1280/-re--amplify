"""LiquidationOracle facade.

Primary path (reAmplify new vault): Zero-Borrow Cell / vault lifecycle monitoring
via ``evaluate_vault`` / ``evaluate_cell`` — no Aave, no Internal HF.

Optional Borrow-Enabled (Board-authorized B.1.2 only):
``evaluate_depositor_borrow_enabled`` — quarantined; requires explicit mode flip.
"""

from __future__ import annotations

import logging
from typing import Any

from reamplify_oracle.cell_monitor import (
    CellProgrammeConfig,
    CellVaultMonitor,
    ZeroBorrowReport,
)
from reamplify_oracle.config import OperatingMode, OracleConfig
from reamplify_oracle.divergence import DivergenceTracker
from reamplify_oracle.escalation import emit_zone_alerts
from reamplify_oracle.health_factor import build_hf_report, resolve_collateral_factor
from reamplify_oracle.indexer_client import IndexerClient
from reamplify_oracle.insurance_returns import InsuranceReturnsOracle
from reamplify_oracle.models import HealthFactorReport, PositionState
from reamplify_oracle.price_oracle import BtcReferencePriceOracle
from reamplify_oracle.redemption import RedemptionEngine
from reamplify_oracle.spoke_hf import SpokeHealthFactorProvider, StubSpokeHealthFactorProvider

logger = logging.getLogger(__name__)


class LiquidationOracle:
    """reAmplify oracle facade — Zero-Borrow by default."""

    def __init__(
        self,
        config: OracleConfig | None = None,
        *,
        indexer: IndexerClient | None = None,
        price_oracle: BtcReferencePriceOracle | None = None,
        spoke_hf_provider: SpokeHealthFactorProvider | None = None,
        redemption: RedemptionEngine | None = None,
    ) -> None:
        self.config = config or OracleConfig()
        self.indexer = indexer or IndexerClient(self.config.indexer)
        self.price_oracle = price_oracle or BtcReferencePriceOracle(self.config.btc_reference)
        self.spoke_hf_provider: SpokeHealthFactorProvider = (
            spoke_hf_provider or StubSpokeHealthFactorProvider()
        )
        self.redemption = redemption or RedemptionEngine(
            self.config.timing, mode=self.config.mode
        )
        self.insurance = InsuranceReturnsOracle()
        self.divergence = DivergenceTracker(self.config.divergence)
        self.cell_monitor = CellVaultMonitor(self.config, self.indexer, self.price_oracle)
        self._owns_defaults = indexer is None

    def close(self) -> None:
        self.indexer.close()
        self.price_oracle.close()

    def __enter__(self) -> "LiquidationOracle":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def set_mode(self, mode: OperatingMode | str) -> None:
        mode_e = OperatingMode(str(mode).upper())
        if mode_e == OperatingMode.BORROW_ENABLED:
            logger.warning(
                "BORROW_ENABLED requires Board authorization (B.1.2). "
                "reAmplify new vault default is ZERO_BORROW."
            )
        self.config.mode = mode_e
        self.redemption.mode = mode_e

    # ----- Zero-Borrow primary API (A.2.1 / B.1.1) -----

    def register_cell(self, programme: CellProgrammeConfig) -> CellProgrammeConfig:
        """Register a reAmplify Cell vault programme (Zero-Borrow default)."""
        return self.cell_monitor.register_cell(programme)

    def evaluate_vault(self, vault_id: str, *, cell_id: str | None = None) -> ZeroBorrowReport:
        cell = self.cell_monitor.programmes.get(cell_id) if cell_id else None
        report = self.cell_monitor.evaluate_vault(vault_id, cell=cell)
        self._maybe_path2_from_zero_borrow(report)
        return report

    def evaluate_cell(
        self,
        cell: CellProgrammeConfig | str | None = None,
        *,
        depositor_address: str | None = None,
        vault_ids: list[str] | None = None,
    ) -> ZeroBorrowReport:
        """Evaluate a Cell programme without requiring aavePosition."""
        if cell is None:
            cell = CellProgrammeConfig(
                cell_id="ad-hoc",
                name="ad-hoc",
                mode=self.config.mode,
                depositor_address=depositor_address,
                vault_ids=list(vault_ids or []),
            )
        elif isinstance(cell, str):
            pass  # cell_id looked up inside monitor
        report = self.cell_monitor.evaluate_cell(cell)
        self._maybe_path2_from_zero_borrow(report)
        return report

    def _maybe_path2_from_zero_borrow(self, report: ZeroBorrowReport) -> None:
        """Liquidation under Zero-Borrow is rare/unexpected — still open Path 2 incident."""
        liquidated = [v for v in report.vaults if v.is_liquidated]
        if not liquidated:
            return
        try:
            incident = self.redemption.open_path2_liquidation_incident(
                depositor_address=liquidated[0].depositor,
                vault_ids=[v.vault_id for v in liquidated],
                metadata={
                    "source": "zero_borrow_monitor",
                    "note": "Unexpected liquidation under Zero-Borrow",
                },
                force=True,
            )
            report.alerts.append(
                {
                    "type": "PATH2_INCIDENT_OPENED",
                    "incident_id": incident.incident_id,
                    "status": incident.status.value,
                    "auto_revert_zero_borrow": incident.auto_revert_zero_borrow,
                }
            )
            self.config.mode = OperatingMode.ZERO_BORROW
            self.redemption.mode = OperatingMode.ZERO_BORROW
        except Exception as exc:  # noqa: BLE001
            logger.exception("Path 2 auto-open failed: %s", exc)
            report.notes.append(f"Path 2 auto-open failed: {exc}")

    # ----- Borrow-Enabled (optional, Board-authorized B.1.2) -----

    def evaluate_depositor_borrow_enabled(
        self, depositor_address: str
    ) -> HealthFactorReport:
        """Internal HF monitoring — ONLY when Board has authorized BORROW_ENABLED.

        Raises if current mode is ZERO_BORROW. Prefer ``evaluate_vault`` / ``evaluate_cell``.
        """
        if self.config.mode != OperatingMode.BORROW_ENABLED:
            raise RuntimeError(
                "evaluate_depositor_borrow_enabled requires OperatingMode.BORROW_ENABLED "
                "(Board authorization per B.1.2). reAmplify default is ZERO_BORROW — "
                "use evaluate_vault() / evaluate_cell() instead."
            )
        return self._evaluate_borrow_enabled(depositor_address)

    def evaluate_depositor(self, depositor_address: str) -> HealthFactorReport | ZeroBorrowReport:
        """Compatibility entrypoint.

        - ZERO_BORROW → ``evaluate_cell`` for depositor's vaults (no HF / not CRITICAL)
        - BORROW_ENABLED → Internal HF path
        """
        if self.config.mode == OperatingMode.ZERO_BORROW:
            return self.evaluate_cell(depositor_address=depositor_address)
        return self._evaluate_borrow_enabled(depositor_address)

    def _evaluate_borrow_enabled(self, depositor_address: str) -> HealthFactorReport:
        """Quarantined Borrow-Enabled path — uses optional indexer aave* entities."""
        btc_ref = self.price_oracle.fetch()
        debt_prices = dict(self.config.debt_asset_usd_prices)
        if "2" not in debt_prices:
            debt_prices["2"] = btc_ref.price_usd

        position = self.indexer.fetch_position_state(
            depositor_address,
            debt_usd_prices=debt_prices,
            btc_usd=btc_ref.price_usd,
        )

        # No aavePosition / no debt → clean Zero-Borrow posture (never CRITICAL)
        if position.proxy_contract is None and position.is_zero_debt:
            report = build_hf_report(
                position,
                mode=OperatingMode.ZERO_BORROW,
                collateral_factor=0.0,
                btc_ref=btc_ref,
                escalation=self.config.escalation,
                spoke_hf=None,
            )
            report.operating_mode = OperatingMode.BORROW_ENABLED.value
            report.notes.append(
                "No aavePosition / no outstanding debt — reporting Zero-Borrow posture "
                "(not CRITICAL). BORROW_ENABLED HF N/A until debt exists."
            )
            emit_zone_alerts(report)
            return report

        if position.is_zero_debt:
            report = build_hf_report(
                position,
                mode=OperatingMode.BORROW_ENABLED,
                collateral_factor=0.0,
                btc_ref=btc_ref,
                escalation=self.config.escalation,
                spoke_hf=None,
            )
            # classify_zone with hf=None → ZERO_BORROW
            emit_zone_alerts(report)
            self.divergence.evaluate(report)
            return report

        reserves = self.indexer.get_reserves()
        cf = resolve_collateral_factor(
            reserves,
            override_bps=self.config.collateral_factor_override_bps,
        )
        spoke_hf = self.spoke_hf_provider.get_spoke_health_factor(depositor_address)
        report = build_hf_report(
            position,
            mode=OperatingMode.BORROW_ENABLED,
            collateral_factor=cf,
            btc_ref=btc_ref,
            escalation=self.config.escalation,
            spoke_hf=spoke_hf,
        )
        emit_zone_alerts(report)
        self.divergence.evaluate(report)

        if position.has_liquidation_activity or position.liquidated_vault_ids:
            try:
                incident = self.redemption.maybe_trigger_path2_from_position(position)
                if incident:
                    report.alerts.append(
                        {
                            "type": "PATH2_INCIDENT_OPENED",
                            "incident_id": incident.incident_id,
                            "status": incident.status.value,
                            "auto_revert_zero_borrow": incident.auto_revert_zero_borrow,
                        }
                    )
                    self.config.mode = OperatingMode.ZERO_BORROW
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to open Path 2 incident: %s", exc)
                report.notes.append(f"Path 2 auto-open failed: {exc}")

        if position.freshness:
            report.notes.append(
                f"Indexer freshness: chain={position.freshness.chain_id} "
                f"block={position.freshness.block_number}"
            )
        return report

    def summary(self, report: HealthFactorReport | ZeroBorrowReport) -> dict[str, Any]:
        return report.to_dict()
