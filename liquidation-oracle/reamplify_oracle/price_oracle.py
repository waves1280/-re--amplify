"""BTC Reference Price (A.3.4 / B.5) — NOT for Insurance Return calculations.

≥2 independent sources (CoinGecko + Coinbase public APIs), median/mean aggregate.
Detect ≥50% decline vs Board-approved baseline → recommend suspend new policies.
"""

from __future__ import annotations

import logging
import statistics
from typing import Protocol

import httpx

from reamplify_oracle.config import BtcReferenceConfig
from reamplify_oracle.models import BtcReferencePrice

logger = logging.getLogger(__name__)


class PriceSource(Protocol):
    name: str

    def fetch_btc_usd(self, client: httpx.Client) -> float: ...


class CoinGeckoSource:
    name = "coingecko"
    URL = "https://api.coingecko.com/api/v3/simple/price"

    def fetch_btc_usd(self, client: httpx.Client) -> float:
        r = client.get(
            self.URL,
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            headers={"Accept": "application/json", "User-Agent": "reamplify-liquidation-oracle/0.1.0"},
        )
        r.raise_for_status()
        return float(r.json()["bitcoin"]["usd"])


class CoinbaseSource:
    name = "coinbase"
    URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot"

    def fetch_btc_usd(self, client: httpx.Client) -> float:
        r = client.get(
            self.URL,
            headers={"Accept": "application/json", "User-Agent": "reamplify-liquidation-oracle/0.1.0"},
        )
        r.raise_for_status()
        return float(r.json()["data"]["amount"])


class BtcReferencePriceOracle:
    """Aggregates ≥2 public BTC/USD feeds. Never used for Insurance Returns."""

    def __init__(
        self,
        config: BtcReferenceConfig | None = None,
        *,
        client: httpx.Client | None = None,
        sources: list[PriceSource] | None = None,
    ) -> None:
        self.config = config or BtcReferenceConfig()
        self._owns = client is None
        self._client = client or httpx.Client(timeout=20.0)
        if sources is not None:
            self.sources = sources
        else:
            self.sources = []
            if self.config.coingecko_enabled:
                self.sources.append(CoinGeckoSource())
            if self.config.coinbase_enabled:
                self.sources.append(CoinbaseSource())

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def fetch(self) -> BtcReferencePrice:
        if len(self.sources) < 2:
            logger.warning(
                "Fewer than 2 BTC price sources enabled (%d); policy prefers ≥2 (A.3.4)",
                len(self.sources),
            )
        quotes: dict[str, float] = {}
        errors: list[str] = []
        for src in self.sources:
            try:
                quotes[src.name] = src.fetch_btc_usd(self._client)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{src.name}: {exc}")
                logger.warning("BTC price source %s failed: %s", src.name, exc)

        if not quotes:
            raise RuntimeError(f"All BTC reference price sources failed: {errors}")

        values = list(quotes.values())
        method = self.config.aggregate.lower()
        if method == "mean":
            agg = float(statistics.mean(values))
        else:
            agg = float(statistics.median(values))
            method = "median"

        baseline = self.config.baseline_usd
        if baseline <= 0:
            decline = 0.0
        else:
            decline = max(0.0, (baseline - agg) / baseline * 100.0)
        suspend = decline >= self.config.crash_threshold_pct

        return BtcReferencePrice(
            price_usd=agg,
            sources=quotes,
            aggregate_method=method,
            baseline_usd=baseline,
            decline_vs_baseline_pct=decline,
            recommend_suspend_new_policies=suspend,
        )
