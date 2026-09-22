"""Babylon TBV Vault Indexer GraphQL client.

Primary (Zero-Borrow / A.2.1): vault, vaults, vaultActivitys, vaultProvider, fees, _meta.
Optional (Borrow-Enabled / Board-authorized B.1.2 only): aavePosition*, aaveReserve*, aaveVaultStatus*.

Client rules:
- POST GraphQL, Content-Type application/json
- Custom User-Agent required (default clients get 403)
- limit capped at 1000; page with offset
- Depth ≤ 10
- BigInt fields arrive as strings
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from reamplify_oracle.config import IndexerConfig
from reamplify_oracle.models import (
    CollateralSlice,
    IndexerFreshness,
    PositionState,
    ReserveInfo,
)

logger = logging.getLogger(__name__)

MAX_LIMIT = 1000


class IndexerError(RuntimeError):
    pass


class IndexerClient:
    def __init__(
        self,
        config: IndexerConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or IndexerConfig()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.config.url.rstrip("/") + "/",
            timeout=self.config.timeout_seconds,
            headers={
                "Content-Type": "application/json",
                "User-Agent": self.config.user_agent,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "IndexerClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        logger.debug("GraphQL POST %s", self.config.url)
        resp = self._client.post("", json=payload)
        if resp.status_code == 403:
            raise IndexerError(
                "Indexer returned 403 — ensure a custom User-Agent is set "
                f"(current={self.config.user_agent!r})"
            )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body and body["errors"]:
            raise IndexerError(f"GraphQL errors: {body['errors']}")
        return body.get("data") or {}

    def get_meta(self) -> IndexerFreshness:
        data = self.execute("{ _meta { status } }")
        status = (data.get("_meta") or {}).get("status") or {}
        chain_id = None
        block_number = None
        block_timestamp = None
        # status is typically { "<network>": { id, block: { number, timestamp } } }
        if isinstance(status, dict):
            for key, val in status.items():
                if isinstance(val, dict) and "block" in val:
                    chain_id = str(val.get("id") or key)
                    block = val.get("block") or {}
                    block_number = _as_int(block.get("number"))
                    block_timestamp = _as_int(block.get("timestamp"))
                    break
        return IndexerFreshness(
            raw_status=status if isinstance(status, dict) else {"raw": status},
            chain_id=chain_id,
            block_number=block_number,
            block_timestamp=block_timestamp,
        )

    def get_aave_position(self, depositor_address: str) -> dict[str, Any] | None:
        """Optional Borrow-Enabled only (B.1.2). Not used for Zero-Borrow Cell monitoring."""
        query = """
        query AavePosition($addr: String!) {
          aavePosition(depositorAddress: $addr) {
            depositorAddress
            proxyContract
            totalCollateral
            createdAt
            updatedAt
            blockNumber
            transactionHash
            collaterals(limit: 1000, offset: 0, where: { removedAt: null }) {
              items {
                vaultId
                amount
                addedAt
                removedAt
                liquidationIndex
                vault {
                  id
                  status
                  amount
                  depositor
                  inUse
                }
              }
              totalCount
            }
          }
        }
        """
        data = self.execute(query, {"addr": depositor_address.lower()})
        return data.get("aavePosition")

    def get_aave_vault_status(self, vault_id: str) -> dict[str, Any] | None:
        query = """
        query VaultStatus($vid: String!) {
          aaveVaultStatus(vaultId: $vid) {
            vaultId
            applicationEntryPoint
            status
            metadata
            updatedAt
          }
        }
        """
        data = self.execute(query, {"vid": vault_id})
        return data.get("aaveVaultStatus")

    def get_aave_vault_statuses(
        self, vault_ids: list[str] | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        # Note: plural field is `aaveVaultStatuss` (indexer spelling).
        limit = min(limit, MAX_LIMIT)
        if vault_ids:
            items: list[dict[str, Any]] = []
            for vid in vault_ids:
                st = self.get_aave_vault_status(vid)
                if st:
                    items.append(st)
            return items
        query = """
        query VaultStatuses($limit: Int!, $offset: Int!) {
          aaveVaultStatuss(limit: $limit, offset: $offset) {
            items {
              vaultId
              applicationEntryPoint
              status
              metadata
              updatedAt
            }
            totalCount
          }
        }
        """
        data = self.execute(query, {"limit": limit, "offset": offset})
        page = data.get("aaveVaultStatuss") or {}
        return list(page.get("items") or [])

    def get_reserves(self) -> dict[str, ReserveInfo]:
        query = """
        {
          aaveReserves(limit: 1000, offset: 0) {
            items {
              id
              underlying
              decimals
              collateralFactor
              borrowable
              paused
              frozen
              underlyingToken { address symbol name decimals }
            }
          }
        }
        """
        data = self.execute(query)
        out: dict[str, ReserveInfo] = {}
        for item in (data.get("aaveReserves") or {}).get("items") or []:
            rid = str(item["id"])
            tok = item.get("underlyingToken") or {}
            out[rid] = ReserveInfo(
                reserve_id=rid,
                underlying=item["underlying"],
                decimals=int(item["decimals"]),
                collateral_factor_bps=int(item.get("collateralFactor") or 0),
                symbol=tok.get("symbol"),
                borrowable=bool(item.get("borrowable")),
            )
        return out

    def iter_vault_activities(
        self,
        *,
        depositor: str | None = None,
        vault_id: str | None = None,
        activity_type: str | None = None,
        page_size: int | None = None,
    ):
        """Yield vaultActivity rows with offset pagination (limit ≤ 1000)."""
        page_size = min(page_size or self.config.page_limit, MAX_LIMIT)
        offset = 0
        where: dict[str, Any] = {}
        if depositor:
            where["depositor"] = depositor.lower()
        if vault_id:
            where["vaultId"] = vault_id
        if activity_type:
            where["type"] = activity_type

        query = """
        query Activities($where: vaultActivityFilter, $limit: Int!, $offset: Int!) {
          vaultActivitys(
            where: $where
            limit: $limit
            offset: $offset
            orderBy: "timestamp"
            orderDirection: "asc"
          ) {
            items {
              id
              vaultId
              depositor
              type
              amount
              debtReserveId
              timestamp
              blockNumber
              transactionHash
            }
            totalCount
          }
        }
        """
        while True:
            data = self.execute(
                query, {"where": where or None, "limit": page_size, "offset": offset}
            )
            page = data.get("vaultActivitys") or {}
            items = page.get("items") or []
            for item in items:
                yield item
            if len(items) < page_size:
                break
            offset += page_size
            total = page.get("totalCount")
            if total is not None and offset >= int(total):
                break


    def get_vault(self, vault_id: str) -> dict[str, Any] | None:
        """Fetch a single vault lifecycle record (Zero-Borrow primary)."""
        query = """
        query Vault($vid: String!) {
          vault(id: $vid) {
            id
            status
            amount
            depositor
            vaultProvider
            vaultProviderCommissionBps
            maxAcceptableCommissionBps
            ackCount
            inUse
            applicationEntryPoint
            pendingAt
            verifiedAt
            activatedAt
            expiredAt
            expirationReason
            claimExpiredUntil
            expiredClaimedAt
            peginTxHash
            blockNumber
            transactionHash
          }
        }
        """
        data = self.execute(query, {"vid": vault_id})
        return data.get("vault")

    def get_vault_provider(self, provider_id: str) -> dict[str, Any] | None:
        query = """
        query Provider($id: String!) {
          vaultProvider(id: $id) {
            id
            name
            commissionBps
            applicationEntryPoint
            metadataStatus
            registeredAt
          }
        }
        """
        data = self.execute(query, {"id": provider_id})
        return data.get("vaultProvider")

    def get_vault_fee_escrow(self, vault_id: str) -> dict[str, Any] | None:
        query = """
        query FeeEscrow($vid: String!) {
          vaultFeeEscrow(vaultId: $vid) {
            vaultId
            totalAmount
            vaultProvider
            numUniversalChallengers
            numAppVaultKeepers
            status
            escrowedAt
            distributedAt
            refundedAt
            forfeitedAt
          }
        }
        """
        data = self.execute(query, {"vid": vault_id})
        return data.get("vaultFeeEscrow")

    def get_fee_configs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        limit = min(limit, MAX_LIMIT)
        query = """
        query FeeConfigs($limit: Int!) {
          feeConfigs(limit: $limit, offset: 0) {
            items {
              id
              vpFeeRate
              ucFeeRate
              avkFeeRate
              protocolPegInFeeRate
              vpRegistrationFee
              updatedAt
            }
          }
        }
        """
        data = self.execute(query, {"limit": limit})
        return list((data.get("feeConfigs") or {}).get("items") or [])

    def get_vaults_for_depositor(self, depositor: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = min(limit, MAX_LIMIT)
        query = """
        query Vaults($dep: String!, $limit: Int!) {
          vaults(where: { depositor: $dep }, limit: $limit, offset: 0) {
            items {
              id
              status
              amount
              depositor
              inUse
              applicationEntryPoint
            }
            totalCount
          }
        }
        """
        data = self.execute(query, {"dep": depositor.lower(), "limit": limit})
        return list((data.get("vaults") or {}).get("items") or [])

    def fetch_position_state(
        self,
        depositor_address: str,
        *,
        debt_usd_prices: dict[str, float] | None = None,
        btc_usd: float | None = None,
    ) -> PositionState:
        """Assemble full position: collaterals, vault statuses, debt from activities, meta."""
        addr = depositor_address.lower()
        freshness = self.get_meta()
        position = self.get_aave_position(addr)
        reserves = self.get_reserves()

        collaterals: list[CollateralSlice] = []
        total_collateral_sats = 0
        proxy = None
        liquidated_vault_ids: list[str] = []

        if position:
            proxy = position.get("proxyContract")
            total_collateral_sats = _as_int(position.get("totalCollateral")) or 0
            items = ((position.get("collaterals") or {}).get("items")) or []
            vault_ids = [c["vaultId"] for c in items]
            status_map = {
                s["vaultId"]: s for s in self.get_aave_vault_statuses(vault_ids)
            }
            for c in items:
                vault = c.get("vault") or {}
                vstatus = vault.get("status")
                if vstatus == "liquidated":
                    liquidated_vault_ids.append(c["vaultId"])
                amount = _as_int(c.get("amount")) or 0
                collaterals.append(
                    CollateralSlice(
                        vault_id=c["vaultId"],
                        amount_sats=amount,
                        vault_status=vstatus,
                        aave_vault_status=(status_map.get(c["vaultId"]) or {}).get("status"),
                        liquidation_index=int(c.get("liquidationIndex") or 0),
                        in_use=vault.get("inUse"),
                    )
                )

        # Reconstruct outstanding debt: net borrow − repay per debtReserveId
        from reamplify_oracle.models import DebtByReserve

        nets: dict[str, int] = {}
        activity_summary: dict[str, int] = {}
        has_liquidation = False
        for act in self.iter_vault_activities(depositor=addr):
            atype = act.get("type") or ""
            activity_summary[atype] = activity_summary.get(atype, 0) + 1
            if atype == "liquidation":
                has_liquidation = True
                if act.get("vaultId"):
                    liquidated_vault_ids.append(act["vaultId"])
            if atype not in {"borrow", "repay"}:
                continue
            rid = act.get("debtReserveId")
            if rid is None:
                continue
            rid = str(rid)
            amt = _as_int(act.get("amount")) or 0
            if atype == "borrow":
                nets[rid] = nets.get(rid, 0) + amt
            else:
                nets[rid] = nets.get(rid, 0) - amt

        debt_prices = debt_usd_prices or {}
        debt_rows: list[DebtByReserve] = []
        for rid, net in sorted(nets.items(), key=lambda x: x[0]):
            if net <= 0:
                # Fully repaid (or over-repaid in indexer reconstruction) → no outstanding
                continue
            info = reserves.get(rid)
            decimals = info.decimals if info else 18
            symbol = info.symbol if info else None
            human = net / (10**decimals)
            if rid in debt_prices:
                px = debt_prices[rid]
            elif symbol and symbol.upper() in {"USDC", "USDT", "DAI"}:
                px = 1.0
            elif symbol and symbol.upper() in {"WBTC", "BTC", "VAULTBTC"}:
                px = float(btc_usd) if btc_usd is not None else 0.0
            else:
                px = float(debt_prices.get(rid, 0.0))
            debt_rows.append(
                DebtByReserve(
                    reserve_id=rid,
                    net_raw=net,
                    decimals=decimals,
                    symbol=symbol,
                    usd_value=human * px,
                )
            )

        # Dedupe liquidated vault ids
        liquidated_vault_ids = list(dict.fromkeys(liquidated_vault_ids))

        return PositionState(
            depositor_address=addr,
            proxy_contract=proxy,
            total_collateral_sats=total_collateral_sats,
            collaterals=collaterals,
            debt_by_reserve=debt_rows,
            activity_summary=activity_summary,
            has_liquidation_activity=has_liquidation or bool(liquidated_vault_ids),
            liquidated_vault_ids=liquidated_vault_ids,
            freshness=freshness,
        )


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))
