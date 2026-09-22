import httpx

from reamplify_oracle.config import BtcReferenceConfig
from reamplify_oracle.price_oracle import BtcReferencePriceOracle, CoinbaseSource, CoinGeckoSource


class FixedSource:
    def __init__(self, name: str, price: float):
        self.name = name
        self.price = price

    def fetch_btc_usd(self, client: httpx.Client) -> float:
        return self.price


def test_median_and_crash_flag():
    cfg = BtcReferenceConfig(baseline_usd=100_000, crash_threshold_pct=50, aggregate="median")
    oracle = BtcReferencePriceOracle(
        cfg,
        sources=[FixedSource("a", 40_000), FixedSource("b", 50_000), FixedSource("c", 42_000)],
    )
    ref = oracle.fetch()
    assert ref.price_usd == 42_000
    assert ref.recommend_suspend_new_policies is True
    assert "NOT for Insurance Return" in ref.note


def test_live_source_classes_parse(httpx_mock):
    httpx_mock.add_response(
        url="https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
        json={"bitcoin": {"usd": 95000.5}},
    )
    httpx_mock.add_response(
        url="https://api.coinbase.com/v2/prices/BTC-USD/spot",
        json={"data": {"amount": "95100.0"}},
    )
    with httpx.Client() as client:
        assert CoinGeckoSource().fetch_btc_usd(client) == 95000.5
        assert CoinbaseSource().fetch_btc_usd(client) == 95100.0
