"""reAmplify Liquidation Oracle & Redemption Rules.

Default posture: ZERO_BORROW for the reAmplify vault / Cell programme (A.2.1 / B.1.1).
Uses Babylon Vault Indexer ``vault*`` entities. Borrow-Enabled / Internal HF is
optional and Board-authorized (B.1.2) — no external lending-protocol debt feed.

Optional on-chain path: RiskOracleKeeper publishes monitoring snapshots to
ReamplifyRiskOracle — does NOT replace Spoke/Chainlink liquidation pricing.
"""

from __future__ import annotations

__version__ = "0.2.0"

from reamplify_oracle.cell_monitor import CellProgrammeConfig, CellVaultMonitor, ZeroBorrowReport
from reamplify_oracle.config import OracleConfig, OperatingMode
from reamplify_oracle.oracle import LiquidationOracle
from reamplify_oracle.redemption import RedemptionEngine

__all__ = [
    "__version__",
    "OracleConfig",
    "OperatingMode",
    "LiquidationOracle",
    "RedemptionEngine",
    "CellProgrammeConfig",
    "CellVaultMonitor",
    "ZeroBorrowReport",
]

# Optional keeper import (requires web3 only at use-time)
try:
    from reamplify_oracle.keeper import RiskOracleKeeper, OnChainRiskSnapshot

    __all__ += ["RiskOracleKeeper", "OnChainRiskSnapshot"]
except Exception:  # pragma: no cover — keeper module has no hard web3 dep at import
    pass
