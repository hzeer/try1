# try1

## Adaptive VWAP Algorithm (Saudi Aramco / TADAWUL 2222)

This repository now includes a practical Python implementation of an **adaptive VWAP execution model** for Saudi Aramco that:

- Anchors to a **90-day intraday volume pattern**.
- Adapts to **daily market move** (trend from open).
- Adapts to **spread conditions** (wider spreads reduce aggression).
- Keeps execution aligned to the parent order target by end-of-session.

### File

- `adaptive_vwap_saudi_aramco.py`

### Run example

```bash
python3 adaptive_vwap_saudi_aramco.py
```
