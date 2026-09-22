# -re--amplify
Enhance your yield on any token asset

## Liquidation oracle

Zero-Borrow Cell monitor and redemption engine (Babylon TBV Vault Indexer) lives in [`liquidation-oracle/`](./liquidation-oracle/).

```bash
cd liquidation-oracle
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python examples/demo_live.py
```
