"""Configuration via env + YAML/JSON. Policy: B.1 modes, A.4 thresholds, A.5 divergence, B.5 price."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


class OperatingMode(str, Enum):
    """B.1 operating modes.

    ZERO_BORROW — default for reAmplify new vault (B.1.1). No debt / no HF.
    BORROW_ENABLED — optional; requires Board authorization (B.1.2).
    """

    ZERO_BORROW = "ZERO_BORROW"
    BORROW_ENABLED = "BORROW_ENABLED"


@dataclass
class IndexerConfig:
    url: str = "https://babylon-vault-indexer-api.testnet.babylonlabs.io/"
    user_agent: str = "reamplify-liquidation-oracle/0.1.0 (reAmplify; Joshua)"
    timeout_seconds: float = 30.0
    page_limit: int = 1000
    max_depth: int = 10


@dataclass
class BtcReferenceConfig:
    baseline_usd: float = 100_000.0
    crash_threshold_pct: float = 50.0
    aggregate: str = "median"  # median | mean
    coingecko_enabled: bool = True
    coinbase_enabled: bool = True


@dataclass
class DivergenceConfig:
    tolerance: float = 0.05
    persistence_days: int = 5


@dataclass
class EscalationConfig:
    green_min: float = 3.0
    red_min: float = 1.5
    spoke_liquidatable_threshold: float = 1.0


@dataclass
class TimingConstants:
    """Documented timing constants (Part B)."""

    csa_support_notice_business_days: int = 2
    tbv_challenge_approx_days: int = 3
    pegin_refund_timelock_calendar_days: int = 14
    path1_notice_calendar_days: int = 30
    path2_postmortem_business_days: int = 5


@dataclass
class CellConfig:
    """Optional default Cell programme from YAML (Zero-Borrow primary)."""

    cell_id: str = "reamplify-cell-1"
    name: str = "reAmplify Cell"
    depositor_address: str | None = None
    vault_ids: list[str] = field(default_factory=list)


@dataclass
class OracleConfig:
    mode: OperatingMode = OperatingMode.ZERO_BORROW
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    cell: CellConfig = field(default_factory=CellConfig)
    # --- Borrow-Enabled only (B.1.2) ---
    collateral_factor_override_bps: int | None = None
    debt_asset_usd_prices: dict[str, float] = field(
        default_factory=lambda: {"0": 1.0, "1": 1.0}
    )
    btc_reference: BtcReferenceConfig = field(default_factory=BtcReferenceConfig)
    divergence: DivergenceConfig = field(default_factory=DivergenceConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    timing: TimingConstants = field(default_factory=TimingConstants)
    log_level: str = "INFO"
    json_logs: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OracleConfig":
        mode_raw = data.get("mode", "ZERO_BORROW")
        mode = OperatingMode(str(mode_raw).upper())

        idx = data.get("indexer") or {}
        indexer = IndexerConfig(
            url=idx.get("url", IndexerConfig.url),
            user_agent=idx.get("user_agent", IndexerConfig.user_agent),
            timeout_seconds=float(idx.get("timeout_seconds", 30)),
            page_limit=min(int(idx.get("page_limit", 1000)), 1000),
            max_depth=min(int(idx.get("max_depth", 10)), 10),
        )

        btc = data.get("btc_reference") or {}
        sources = btc.get("sources") or []
        cg = True
        cb = True
        if sources:
            by_name = {s.get("name"): s.get("enabled", True) for s in sources if isinstance(s, dict)}
            cg = bool(by_name.get("coingecko", True))
            cb = bool(by_name.get("coinbase", True))
        btc_cfg = BtcReferenceConfig(
            baseline_usd=float(btc.get("baseline_usd", 100_000)),
            crash_threshold_pct=float(btc.get("crash_threshold_pct", 50)),
            aggregate=str(btc.get("aggregate", "median")),
            coingecko_enabled=cg,
            coinbase_enabled=cb,
        )

        div = data.get("divergence") or {}
        esc = data.get("escalation") or {}
        timing_raw = data.get("timing_constants_business_days") or data.get("timing") or {}
        log = data.get("logging") or {}

        prices = data.get("debt_asset_usd_prices") or {"0": 1.0, "1": 1.0}
        prices = {str(k): float(v) for k, v in prices.items()}

        cf_override = data.get("collateral_factor_override_bps")
        if cf_override is not None:
            cf_override = int(cf_override)

        cell_raw = data.get("cell") or {}
        cell = CellConfig(
            cell_id=str(cell_raw.get("cell_id", "reamplify-cell-1")),
            name=str(cell_raw.get("name", "reAmplify Cell")),
            depositor_address=cell_raw.get("depositor_address"),
            vault_ids=list(cell_raw.get("vault_ids") or []),
        )

        return cls(
            mode=mode,
            indexer=indexer,
            cell=cell,
            collateral_factor_override_bps=cf_override,
            debt_asset_usd_prices=prices,
            btc_reference=btc_cfg,
            divergence=DivergenceConfig(
                tolerance=float(div.get("tolerance", 0.05)),
                persistence_days=int(div.get("persistence_days", 5)),
            ),
            escalation=EscalationConfig(
                green_min=float(esc.get("green_min", 3.0)),
                red_min=float(esc.get("red_min", 1.5)),
                spoke_liquidatable_threshold=float(
                    esc.get("spoke_liquidatable_threshold", 1.0)
                ),
            ),
            timing=TimingConstants(
                csa_support_notice_business_days=int(
                    timing_raw.get("csa_support_notice", timing_raw.get("csa_support_notice_business_days", 2))
                ),
                tbv_challenge_approx_days=int(
                    timing_raw.get("tbv_challenge", timing_raw.get("tbv_challenge_approx_days", 3))
                ),
                pegin_refund_timelock_calendar_days=int(
                    timing_raw.get(
                        "pegin_refund_timelock_calendar_days",
                        timing_raw.get("pegin_refund_timelock", 14),
                    )
                ),
                path1_notice_calendar_days=int(
                    timing_raw.get("path1_notice_calendar_days", 30)
                ),
                path2_postmortem_business_days=int(
                    timing_raw.get("path2_postmortem_business_days", 5)
                ),
            ),
            log_level=str(log.get("level", "INFO")),
            json_logs=bool(log.get("json", False)),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "OracleConfig":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            if yaml is None:
                raise RuntimeError("PyYAML required to load YAML config")
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    @classmethod
    def from_env(cls, base: "OracleConfig | None" = None) -> "OracleConfig":
        cfg = base or cls()
        mode = os.getenv("REAMPLIFY_MODE")
        if mode:
            cfg.mode = OperatingMode(mode.upper())
        url = os.getenv("REAMPLIFY_INDEXER_URL")
        if url:
            cfg.indexer.url = url
        ua = os.getenv("REAMPLIFY_USER_AGENT")
        if ua:
            cfg.indexer.user_agent = ua
        baseline = os.getenv("REAMPLIFY_BTC_BASELINE_USD")
        if baseline:
            cfg.btc_reference.baseline_usd = float(baseline)
        level = os.getenv("REAMPLIFY_LOG_LEVEL")
        if level:
            cfg.log_level = level
        return cfg

    def with_mode(self, mode: OperatingMode | str) -> "OracleConfig":
        self.mode = OperatingMode(str(mode).upper())
        return self
