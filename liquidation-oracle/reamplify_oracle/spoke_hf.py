"""Spoke on-chain Health Factor provider stub (A.5 divergence).

*** BORROW-ENABLED ONLY (Board-authorized B.1.2) ***
Not used for Zero-Borrow Cell monitoring. Indexer has NO native HF field.
Wire this to Chainlink / adapter lens later if Board enables borrowing.
Never fabricate on-chain HF values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SpokeHealthFactorProvider(Protocol):
    """Optional callback/RPC adapter interface for Spoke on-chain HF."""

    def get_spoke_health_factor(self, depositor_address: str) -> float | None:
        """Return Spoke HF or None if unavailable / not wired."""
        ...


@dataclass
class StubSpokeHealthFactorProvider:
    """Explicit stub — returns None so divergence stays inactive until wired.

    Replace with an implementation that calls Chainlink / on-chain Spoke adapter /
    Spoke RPC. Do NOT invent HF numbers in production monitoring.
    """

    fixed_value: float | None = None
    note: str = (
        "StubSpokeHealthFactorProvider: no on-chain HF wired. "
        "Indexer GraphQL has no native HF field. Wire Chainlink / Spoke adapter later if Board enables borrowing."
    )

    def get_spoke_health_factor(self, depositor_address: str) -> float | None:
        _ = depositor_address
        return self.fixed_value
