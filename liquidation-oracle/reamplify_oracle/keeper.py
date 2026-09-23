"""On-chain risk oracle keeper / relayer.

Publishes LiquidationOracle / CellVaultMonitor snapshots to ReamplifyRiskOracle.

This does NOT replace Spoke / Babylon / Chainlink liquidation pricing. It only
mirrors monitoring state on-chain for Cell ops and downstream app consumers.

Dry-run is the default. Live sends require dry_run=False AND
REAMPLIFY_KEEPER_LIVE=1. Private key is read from REAMPLIFY_KEEPER_KEY and
never logged.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from reamplify_oracle.cell_monitor import ZeroBorrowReport
from reamplify_oracle.config import OracleConfig
from reamplify_oracle.models import EscalationZone, HealthFactorReport
from reamplify_oracle.oracle import LiquidationOracle

logger = logging.getLogger(__name__)

MAX_UINT256 = (1 << 256) - 1
HF_SCALE = 10**18
BTC_USD_SCALE = 10**8  # 8 decimals
ZERO_ADDRESS = "0x" + ("00" * 20)

ZONE_TO_UINT8: dict[EscalationZone | str, int] = {
    EscalationZone.ZERO_BORROW: 0,
    EscalationZone.GREEN: 1,
    EscalationZone.RED: 2,
    EscalationZone.CRITICAL: 3,
    "ZERO_BORROW": 0,
    "GREEN": 1,
    "RED": 2,
    "CRITICAL": 3,
    "UNKNOWN": 0,  # monitoring default; enum has no UNKNOWN
}

ABI_PATH = Path(__file__).resolve().parent / "abi" / "ReamplifyRiskOracle.json"


@dataclass
class OnChainRiskSnapshot:
    """Encoded args for updateRisk / one batch row."""

    vault_id: bytes  # 32 bytes
    vault_id_hex: str
    depositor: str
    internal_hf: int
    zone: int
    zone_name: str
    btc_ref_price_usd: int
    recommend_suspend_new_policies: bool
    indexer_block: int
    source: str = "zero_borrow"
    notes: list[str] = field(default_factory=list)

    def to_update_args(self) -> tuple[Any, ...]:
        return (
            self.vault_id,
            self.depositor,
            self.internal_hf,
            self.zone,
            self.btc_ref_price_usd,
            self.recommend_suspend_new_policies,
            self.indexer_block,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "vault_id": self.vault_id_hex,
            "depositor": self.depositor,
            "internal_hf": str(self.internal_hf),
            "internal_hf_note": (
                "type(uint256).max / infinite (B.1 Zero-Borrow)"
                if self.internal_hf == MAX_UINT256
                else f"{self.internal_hf / HF_SCALE:.6f} (1e18)"
            ),
            "zone": self.zone,
            "zone_name": self.zone_name,
            "btc_ref_price_usd": self.btc_ref_price_usd,
            "btc_ref_price_usd_human": self.btc_ref_price_usd / BTC_USD_SCALE,
            "recommend_suspend_new_policies": self.recommend_suspend_new_policies,
            "indexer_block": self.indexer_block,
            "source": self.source,
            "notes": list(self.notes),
        }


def zone_to_uint8(zone: EscalationZone | str | None) -> int:
    if zone is None:
        return 0
    if isinstance(zone, EscalationZone):
        return ZONE_TO_UINT8.get(zone, 0)
    return ZONE_TO_UINT8.get(str(zone).upper(), 0)


def encode_internal_hf(hf: float | None) -> int:
    """1e18 fixed-point; None / infinite → type(uint256).max (B.1 Zero-Borrow)."""
    if hf is None:
        return MAX_UINT256
    if hf != hf or hf == float("inf"):  # NaN / +inf
        return MAX_UINT256
    if hf < 0:
        raise ValueError("internal HF cannot be negative")
    return int(hf * HF_SCALE)


def encode_btc_ref_usd(price_usd: float | None) -> int:
    """USD with 8 decimals; 0 if unused."""
    if price_usd is None:
        return 0
    if price_usd <= 0:
        return 0
    return int(price_usd * BTC_USD_SCALE)


def vault_id_to_bytes32(vault_id: str | None) -> tuple[bytes, str]:
    if not vault_id:
        return (b"\x00" * 32, "0x" + ("00" * 32))
    raw = vault_id.strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        hex_part = raw[2:]
    else:
        hex_part = raw
    if len(hex_part) > 64:
        raise ValueError(f"vault_id longer than 32 bytes: {vault_id}")
    hex_part = hex_part.zfill(64)
    return (bytes.fromhex(hex_part), "0x" + hex_part.lower())


def normalize_address(addr: str | None) -> str:
    """Return EIP-55 checksum address (web3 requires checksummed inputs)."""
    if not addr:
        return ZERO_ADDRESS
    a = addr.strip()
    if not a.startswith("0x"):
        a = "0x" + a
    if len(a) != 42:
        raise ValueError(f"invalid address length: {addr}")
    try:
        from web3 import Web3

        return Web3.to_checksum_address(a)
    except ImportError:
        return a.lower()


def load_abi(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or ABI_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def snapshot_from_zero_borrow(
    report: ZeroBorrowReport,
    *,
    vault_id: str | None = None,
) -> list[OnChainRiskSnapshot]:
    """Build one on-chain row per vault in a ZeroBorrowReport."""
    snaps: list[OnChainRiskSnapshot] = []
    zone_name = report.zone.value if report.zone else "ZERO_BORROW"
    zone_u8 = zone_to_uint8(report.zone)
    btc = encode_btc_ref_usd(report.btc_reference.price_usd if report.btc_reference else None)
    suspend = bool(
        report.btc_reference.recommend_suspend_new_policies if report.btc_reference else False
    )
    indexer_block = int(report.freshness.block_number or 0) if report.freshness else 0
    notes = list(report.notes)
    notes.append(
        "Monitoring oracle only — Spoke liquidation still uses Babylon/Chainlink."
    )

    vaults = report.vaults
    if vault_id:
        vaults = [v for v in vaults if v.vault_id == vault_id] or vaults

    if not vaults:
        # Depositor-only cell with no vault rows yet
        depositor = None
        if report.cell and report.cell.depositor_address:
            depositor = report.cell.depositor_address
        vid_bytes, vid_hex = vault_id_to_bytes32(vault_id)
        snaps.append(
            OnChainRiskSnapshot(
                vault_id=vid_bytes,
                vault_id_hex=vid_hex,
                depositor=normalize_address(depositor),
                internal_hf=MAX_UINT256,
                zone=zone_u8,
                zone_name=zone_name,
                btc_ref_price_usd=btc,
                recommend_suspend_new_policies=suspend,
                indexer_block=indexer_block,
                source="zero_borrow",
                notes=notes,
            )
        )
        return snaps

    for v in vaults:
        vid_bytes, vid_hex = vault_id_to_bytes32(v.vault_id)
        snaps.append(
            OnChainRiskSnapshot(
                vault_id=vid_bytes,
                vault_id_hex=vid_hex,
                depositor=normalize_address(v.depositor),
                internal_hf=MAX_UINT256,  # B.1: no debt → max uint
                zone=zone_u8,
                zone_name=zone_name,
                btc_ref_price_usd=btc,
                recommend_suspend_new_policies=suspend,
                indexer_block=indexer_block,
                source="zero_borrow",
                notes=notes
                + ([f"vault_status={v.status}"] if v.status else []),
            )
        )
    return snaps


def snapshot_from_hf_report(report: HealthFactorReport) -> OnChainRiskSnapshot:
    """Build a depositor-level snapshot from Borrow-Enabled HF report."""
    vault_id = None
    if report.position and report.position.collaterals:
        vault_id = report.position.collaterals[0].vault_id
    vid_bytes, vid_hex = vault_id_to_bytes32(vault_id)
    indexer_block = 0
    if report.position and report.position.freshness and report.position.freshness.block_number:
        indexer_block = int(report.position.freshness.block_number)
    btc = encode_btc_ref_usd(report.btc_reference.price_usd if report.btc_reference else None)
    suspend = bool(
        report.btc_reference.recommend_suspend_new_policies if report.btc_reference else False
    )
    zone_name = report.zone.value if report.zone else "UNKNOWN"
    return OnChainRiskSnapshot(
        vault_id=vid_bytes,
        vault_id_hex=vid_hex,
        depositor=normalize_address(report.depositor_address),
        internal_hf=encode_internal_hf(report.internal_hf),
        zone=zone_to_uint8(report.zone),
        zone_name=zone_name,
        btc_ref_price_usd=btc,
        recommend_suspend_new_policies=suspend,
        indexer_block=indexer_block,
        source="borrow_enabled",
        notes=list(report.notes)
        + ["Monitoring oracle only — Spoke liquidation still uses Babylon/Chainlink."],
    )


class RiskOracleKeeper:
    """Relayer: evaluate off-chain → encode updateRisk → dry-run or send."""

    def __init__(
        self,
        config: OracleConfig | None = None,
        *,
        rpc_url: str | None = None,
        private_key: str | None = None,
        contract_address: str | None = None,
        dry_run: bool = True,
        oracle: LiquidationOracle | None = None,
        web3: Any | None = None,
    ) -> None:
        self.config = config or OracleConfig.from_env()
        self.rpc_url = rpc_url or os.getenv("REAMPLIFY_RPC_URL") or os.getenv("WEB3_RPC_URL")
        self.contract_address = (
            contract_address
            or os.getenv("REAMPLIFY_RISK_ORACLE_ADDRESS")
            or ZERO_ADDRESS
        )
        # Never log private_key
        self._private_key = private_key or os.getenv("REAMPLIFY_KEEPER_KEY")
        self.dry_run = dry_run
        self._oracle = oracle
        self._owns_oracle = oracle is None
        self._web3 = web3
        self._contract = None
        self._account = None
        self._abi = load_abi()

    def close(self) -> None:
        if self._owns_oracle and self._oracle is not None:
            self._oracle.close()
            self._oracle = None

    def __enter__(self) -> "RiskOracleKeeper":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def oracle(self) -> LiquidationOracle:
        if self._oracle is None:
            self._oracle = LiquidationOracle(self.config)
            self._owns_oracle = True
        return self._oracle

    def _ensure_web3(self) -> Any:
        if self._web3 is not None:
            return self._web3
        try:
            from web3 import Web3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "web3 is required for encoding/sending. Install with: "
                'pip install "reamplify-liquidation-oracle[keeper]"'
            ) from exc
        if not self.rpc_url and not self.dry_run:
            raise RuntimeError("REAMPLIFY_RPC_URL (or WEB3_RPC_URL) required for live mode")
        # Dry-run can use a dummy provider just for ABI encoding
        provider_url = self.rpc_url or "http://127.0.0.1:8545"
        self._web3 = Web3(Web3.HTTPProvider(provider_url, request_kwargs={"timeout": 30}))
        return self._web3

    def _get_contract(self) -> Any:
        if self._contract is not None:
            return self._contract
        w3 = self._ensure_web3()
        from web3 import Web3

        addr = Web3.to_checksum_address(self.contract_address)
        self._contract = w3.eth.contract(address=addr, abi=self._abi)
        return self._contract

    def build_snapshots_for_vault(self, vault_id: str) -> list[OnChainRiskSnapshot]:
        report = self.oracle.evaluate_vault(vault_id)
        return snapshot_from_zero_borrow(report, vault_id=vault_id)

    def build_snapshots_for_depositor(self, depositor: str) -> list[OnChainRiskSnapshot]:
        report = self.oracle.evaluate_depositor(depositor)
        if isinstance(report, HealthFactorReport):
            return [snapshot_from_hf_report(report)]
        return snapshot_from_zero_borrow(report)

    def encode_update_risk(self, snap: OnChainRiskSnapshot) -> dict[str, Any]:
        """Encode updateRisk calldata (works in dry-run without a live node)."""
        contract = self._get_contract()
        fn = contract.functions.updateRisk(*snap.to_update_args())
        calldata = fn._encode_transaction_data()  # noqa: SLF001 — public encode path
        payload = {
            "to": self.contract_address,
            "method": "updateRisk",
            "args": snap.to_dict(),
            "data": calldata,
            "dry_run": self.dry_run,
        }
        return payload

    def encode_update_risk_batch(self, snaps: Sequence[OnChainRiskSnapshot]) -> dict[str, Any]:
        contract = self._get_contract()
        vault_ids = [s.vault_id for s in snaps]
        depositors = [s.depositor for s in snaps]
        hfs = [s.internal_hf for s in snaps]
        zones = [s.zone for s in snaps]
        btcs = [s.btc_ref_price_usd for s in snaps]
        suspends = [s.recommend_suspend_new_policies for s in snaps]
        blocks = [s.indexer_block for s in snaps]
        fn = contract.functions.updateRiskBatch(
            vault_ids, depositors, hfs, zones, btcs, suspends, blocks
        )
        calldata = fn._encode_transaction_data()  # noqa: SLF001
        return {
            "to": self.contract_address,
            "method": "updateRiskBatch",
            "count": len(snaps),
            "args": [s.to_dict() for s in snaps],
            "data": calldata,
            "dry_run": self.dry_run,
        }

    def _live_allowed(self) -> bool:
        return (not self.dry_run) and os.getenv("REAMPLIFY_KEEPER_LIVE") == "1"

    def publish(
        self,
        snaps: Sequence[OnChainRiskSnapshot],
        *,
        batch: bool | None = None,
    ) -> dict[str, Any]:
        if not snaps:
            return {"status": "empty", "dry_run": self.dry_run}

        use_batch = batch if batch is not None else len(snaps) > 1
        if use_batch:
            payload = self.encode_update_risk_batch(snaps)
        else:
            payload = self.encode_update_risk(snaps[0])

        if self.dry_run or not self._live_allowed():
            if not self.dry_run and os.getenv("REAMPLIFY_KEEPER_LIVE") != "1":
                payload["status"] = "blocked_live_flag"
                payload["note"] = (
                    "dry_run=False but REAMPLIFY_KEEPER_LIVE!=1 — not sending. "
                    "Set REAMPLIFY_KEEPER_LIVE=1 to enable live txs."
                )
            else:
                payload["status"] = "dry_run"
            logger.info(
                "Keeper dry-run %s → %s (%s row(s))",
                payload["method"],
                self.contract_address,
                len(snaps),
            )
            return payload

        if not self._private_key:
            raise RuntimeError("REAMPLIFY_KEEPER_KEY required for live publish")
        if self.contract_address == ZERO_ADDRESS:
            raise RuntimeError("REAMPLIFY_RISK_ORACLE_ADDRESS required for live publish")

        w3 = self._ensure_web3()
        from eth_account import Account
        from web3 import Web3

        account = Account.from_key(self._private_key)
        # Do not log account.key / private key
        contract = self._get_contract()
        if use_batch:
            fn = contract.functions.updateRiskBatch(
                [s.vault_id for s in snaps],
                [s.depositor for s in snaps],
                [s.internal_hf for s in snaps],
                [s.zone for s in snaps],
                [s.btc_ref_price_usd for s in snaps],
                [s.recommend_suspend_new_policies for s in snaps],
                [s.indexer_block for s in snaps],
            )
        else:
            fn = contract.functions.updateRisk(*snaps[0].to_update_args())

        nonce = w3.eth.get_transaction_count(account.address)
        tx = fn.build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": w3.eth.chain_id,
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        payload["status"] = "sent"
        payload["tx_hash"] = tx_hash.hex()
        payload["from"] = account.address
        logger.info("Keeper sent %s tx=%s", payload["method"], payload["tx_hash"])
        return payload

    def publish_vault(self, vault_id: str, *, batch: bool | None = None) -> dict[str, Any]:
        snaps = self.build_snapshots_for_vault(vault_id)
        return self.publish(snaps, batch=batch)

    def publish_depositor(self, depositor: str, *, batch: bool | None = None) -> dict[str, Any]:
        snaps = self.build_snapshots_for_depositor(depositor)
        return self.publish(snaps, batch=batch)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "reAmplify risk oracle keeper — publish monitoring snapshots on-chain. "
            "Default is dry-run (prints calldata). Live requires --live and "
            "REAMPLIFY_KEEPER_LIVE=1."
        )
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--vault", help="Vault id (0x… bytes32 hex)")
    g.add_argument("--depositor", help="Depositor address (0x…)")
    p.add_argument(
        "--live",
        action="store_true",
        help="Attempt live send (also requires REAMPLIFY_KEEPER_LIVE=1)",
    )
    p.add_argument("--batch", action="store_true", help="Force updateRiskBatch")
    p.add_argument("--config", help="Path to OracleConfig YAML/JSON")
    p.add_argument("--rpc-url", help="Override REAMPLIFY_RPC_URL")
    p.add_argument("--contract", help="Override REAMPLIFY_RISK_ORACLE_ADDRESS")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = OracleConfig()
    if args.config:
        config = OracleConfig.from_file(args.config)
    config = OracleConfig.from_env(config)

    dry_run = not args.live
    with RiskOracleKeeper(
        config,
        rpc_url=args.rpc_url,
        contract_address=args.contract,
        dry_run=dry_run,
    ) as keeper:
        if args.vault:
            result = keeper.publish_vault(args.vault, batch=True if args.batch else None)
        else:
            result = keeper.publish_depositor(args.depositor, batch=True if args.batch else None)
        # Never dump env secrets
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
