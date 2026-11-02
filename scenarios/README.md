# Extreme Loss Library

Operational-loss events of **$1m or more** in financial markets and back office, all geographies, 1985 to today.

- **Data:** [`extreme_events.csv`](extreme_events.csv) (GitHub shows it as a table). The same data is in [`extreme_events.json`](extreme_events.json).
- **Rebuild:** `python scenarios/build_extreme_events.py`. Events $10m+ are in `build_extreme_events.py`, and the $1m–10m tier is in `tier2_events.py`.

## Columns you will filter on most

| Column | Meaning |
|---|---|
| `back_office_control_failure` | **Y** when the loss came from a failed operational control. That covers processing, reconciliation, confirmation, settlement, custody and client money, transaction reporting, surveillance, data, IT, pre-trade limits and valuation checks. Benchmark rigging, spoofing, client-pricing conduct and pure concealment cases are **N**. |
| `internal_fraud` | **Y** for Basel "Internal fraud" (rogue trading and concealment by staff). Drop these rows if internal fraud is covered by a separate exercise. |
| `loss_band` | `$1-10m`, `$10-100m`, `$100m-1bn`, `$1bn+` (near misses use exposure). |
| `region` | Europe, Americas, Asia-Pacific, Middle East or Global, based on where the event happened. |
| `loss_usd_m` | Loss in USD m at the average FX rate of the year announced. There is no inflation adjustment. |
| `near_miss`, `exposure_usd_m` | Events where the exposure was large but the realised loss was small. |
| `official_source`, `source_database` | Regulator, prosecutor, court or company record, where one exists. |

For **back-office control failures, excluding internal fraud**, filter `back_office_control_failure = Y` and `internal_fraud = N`.

## Coverage

| Tier | Source | Completeness |
|---|---|---|
| $10m+ (IDs RT, MV, EX, PS, CY, CM, CP, BM, MC, RR, OD, AP) | Curated from public loss lists plus a sweep of FCA, SEC, CFTC, Fed, OCC, FINRA, Korea FSC, ASIC, SFC, ASX and SEBI | Good for large, well-known cases. |
| $1m–10m: FCA (SM01–SM20) | Every FCA fine of $1m+ from 2013 to 2026 on a markets or back-office topic | Complete for that register. Retail mis-selling, insurance, consumer credit, issuer disclosure, retail-bank AML and fines on individuals are excluded. |
| $1m–10m: others (SM21–SM39) | SEC, FINRA, CFTC, ASIC, SFC, BaFin, AMF, Central Bank of Ireland | A targeted sweep, **not complete**. FINRA and the SEC alone issue dozens of $1m+ reporting and records fines a year. |

The $1m–10m tier is therefore UK-heavy. Use it for scenario ideas and control-failure patterns. Do not use it for frequency counts, except within the FCA 2013–2026 subset.

## Market operations back-office view

[`market_ops_bo.csv`](market_ops_bo.csv) holds 62 events where a market-ops back-office validation failed or would have caught the loss. It is ranked for a bank with client and interbank counterparty business, back-to-back hedging and only small own risk-management positions (no trading book).

| Column | Meaning |
|---|---|
| `fit` | **High**: same product and process as a client, back-to-back or payments flow. **Medium**: same validation at a different scale or product, or front-office led. **Low**: needs a large trading book; keep only as a stress anchor. |
| `fit_reason` | Why the event applies to this business model. |
| `exposure_source` | Client, interbank counterparty, back-to-back hedge, payments and nostro, own positions, or regulatory. |
| `product` | FX spot, forwards and swaps; FX options; IR derivatives; structured products; money markets, deposits and loans; interbank transfers and nostro; repo and collateral; or other. |
| `process_step` | The deal lifecycle, from onboarding (capacity, limits) through booking and back-to-back matching, confirmations, price verification, collateral, payment release, instruction verification, nostro reconciliation, client rates and reporting to system change. |
| `validation_failed` | The check that failed. |

Rebuild with `python scenarios/build_market_ops.py` after `build_extreme_events.py`.
