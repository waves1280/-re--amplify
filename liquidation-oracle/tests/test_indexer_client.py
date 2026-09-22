import httpx
import pytest

from reamplify_oracle.config import IndexerConfig
from reamplify_oracle.indexer_client import IndexerClient, IndexerError


def test_user_agent_and_403(httpx_mock):
    cfg = IndexerConfig(url="https://indexer.test/", user_agent="reamplify-test/1.0")
    httpx_mock.add_response(status_code=403, json={"error": "forbidden"})
    with IndexerClient(cfg) as client:
        with pytest.raises(IndexerError, match="403"):
            client.execute("{ _meta { status } }")
    request = httpx_mock.get_request()
    assert request.headers["User-Agent"] == "reamplify-test/1.0"
    assert request.headers["Content-Type"] == "application/json"


def test_bigint_as_string_position(httpx_mock):
    cfg = IndexerConfig(url="https://indexer.test/", user_agent="reamplify-test/1.0")
    httpx_mock.add_response(
        json={
            "data": {
                "aavePosition": {
                    "depositorAddress": "0xabc",
                    "proxyContract": "0xproxy",
                    "totalCollateral": "23744786",
                    "createdAt": "1",
                    "updatedAt": "2",
                    "blockNumber": "3",
                    "transactionHash": "0xh",
                    "collaterals": {"items": [], "totalCount": 0},
                }
            }
        }
    )
    with IndexerClient(cfg) as client:
        pos = client.get_aave_position("0xAbC")
    assert pos["totalCollateral"] == "23744786"


def test_graphql_errors(httpx_mock):
    cfg = IndexerConfig(url="https://indexer.test/", user_agent="ua")
    httpx_mock.add_response(json={"errors": [{"message": "boom"}]})
    with IndexerClient(cfg) as client:
        with pytest.raises(IndexerError, match="boom"):
            client.execute("{ nope }")


def test_fetch_position_debt_reconstruction(httpx_mock):
    cfg = IndexerConfig(url="https://indexer.test/", user_agent="ua")

    def router(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "_meta" in body and "aavePosition" not in body and "vaultActivitys" not in body and "aaveReserves" not in body:
            return httpx.Response(
                200,
                json={"data": {"_meta": {"status": {"sepolia": {"id": 11155111, "block": {"number": 1, "timestamp": 2}}}}}},
            )
        if "aavePosition" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "aavePosition": {
                            "depositorAddress": "0xabc",
                            "proxyContract": "0xp",
                            "totalCollateral": "100000000",
                            "createdAt": "1",
                            "updatedAt": "2",
                            "blockNumber": "3",
                            "transactionHash": "0xh",
                            "collaterals": {
                                "items": [
                                    {
                                        "vaultId": "0xv",
                                        "amount": "100000000",
                                        "addedAt": "1",
                                        "removedAt": None,
                                        "liquidationIndex": 0,
                                        "vault": {
                                            "id": "0xv",
                                            "status": "available",
                                            "amount": "100000000",
                                            "depositor": "0xabc",
                                            "inUse": True,
                                        },
                                    }
                                ],
                                "totalCount": 1,
                            },
                        }
                    }
                },
            )
        if "aaveVaultStatus(" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "aaveVaultStatus": {
                            "vaultId": "0xv",
                            "status": "collateralized",
                            "applicationEntryPoint": "0xe",
                            "metadata": None,
                            "updatedAt": "1",
                        }
                    }
                },
            )
        if "aaveReserves" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "aaveReserves": {
                            "items": [
                                {
                                    "id": "0",
                                    "underlying": "0xusdc",
                                    "decimals": 6,
                                    "collateralFactor": 0,
                                    "borrowable": True,
                                    "paused": False,
                                    "frozen": False,
                                    "underlyingToken": {"symbol": "USDC"},
                                },
                                {
                                    "id": "3",
                                    "underlying": "0xvbtc",
                                    "decimals": 8,
                                    "collateralFactor": 7800,
                                    "borrowable": False,
                                    "paused": False,
                                    "frozen": False,
                                    "underlyingToken": {"symbol": "vaultBTC"},
                                },
                            ]
                        }
                    }
                },
            )
        if "vaultActivitys" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "vaultActivitys": {
                            "items": [
                                {
                                    "id": "1",
                                    "vaultId": None,
                                    "depositor": "0xabc",
                                    "type": "borrow",
                                    "amount": "5000000",
                                    "debtReserveId": "0",
                                    "timestamp": "10",
                                    "blockNumber": "1",
                                    "transactionHash": "0x1",
                                },
                                {
                                    "id": "2",
                                    "vaultId": None,
                                    "depositor": "0xabc",
                                    "type": "repay",
                                    "amount": "2000000",
                                    "debtReserveId": "0",
                                    "timestamp": "11",
                                    "blockNumber": "2",
                                    "transactionHash": "0x2",
                                },
                            ],
                            "totalCount": 2,
                        }
                    }
                },
            )
        return httpx.Response(500, json={"error": f"unhandled {body[:80]}"})

    httpx_mock.add_callback(router, is_reusable=True)

    with IndexerClient(cfg) as client:
        state = client.fetch_position_state("0xAbC", debt_usd_prices={"0": 1.0})

    assert state.total_collateral_sats == 100_000_000
    assert len(state.collaterals) == 1
    assert state.collaterals[0].aave_vault_status == "collateralized"
    assert len(state.debt_by_reserve) == 1
    assert state.debt_by_reserve[0].net_raw == 3_000_000  # 5M - 2M
    assert abs(state.debt_by_reserve[0].usd_value - 3.0) < 1e-9
