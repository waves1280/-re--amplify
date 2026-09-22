"""reAmplify Liquidation Oracle & Redemption Rules.

Default posture: ZERO_BORROW for reAmplify's new vault (A.2.1 / B.1.1).
No Aave required. Borrow-Enabled / Internal HF is optional and Board-authorized (B.1.2).
"""

from __future__ import annotations

__version__ = "0.1.1"

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
