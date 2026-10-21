# Op Risk PoC – market-abuse fines

Probability and impact of regulatory fines for **inside-information** and **market-manipulation** events, for one anonymous bank, built from free public data and updated with the bank's own history (Bayesian).

| Cell | Event | Party fined |
|---|---|---|
| A1 | Inside information | Bank |
| A2 | Inside information | Employee of the bank |
| B1 | Market manipulation | Bank |
| B2 | Market manipulation | Employee of the bank |
| M1 / M2 | All market abuse (A + B + type unknown, e.g. ESMA register) | Bank / Employee |

## Files

| File | What it is |
|---|---|
| `OpRisk_PoC.ipynb` | The workbook: run top to bottom |
| `oprisk_engine.py` | Model code (clustering, threshold, NB frequency, Bayes, severity, Monte Carlo) |
| `extract_sources.py` | Downloads and pre-classifies fines from the ESMA sanctions register and FCA fines tables |
| `build_universe.py` | Builds the bank universe (incl. banks with no events), FX rates, and matches events to banks |
| `inputs/events_candidates.csv` | Reviewed event list: `status` = include / review / exclude per notice |
| `inputs/banks_manual.csv` | Sizes for banks with no free source (Standard Chartered, Nationwide, Macquarie) – optional |
| `inputs/coverage.csv` | Years actually searched per region (2013–2025) |
| `demo_data.py` | Synthetic data so the workbook runs before real data exists |
| `inputs/bank_profile.csv` | **Your bank, anonymous**: year, total assets (EUR bn), whether internal data exists, internal event counts per cell |
| `inputs/fx_rates.csv` | FX to EUR (approximate defaults – replace with ECB annual averages) |
| `inputs/*_TEMPLATE.csv` | Formats for peer panel, peer name aliases, and the reviewed event list |
| `oprisk_poc_spec.md` | The agreed specification |

Requirements: Python 3.9+, `pandas numpy scipy matplotlib` and Jupyter. No paid data, no other packages.

## Quick start (demo)

```
cd oprisk_poc
jupyter notebook OpRisk_PoC.ipynb      # or open it in VS Code / PyCharm
```
Run all cells. `DATA_MODE = "DEMO"` uses synthetic data – figures are illustrative only.

## Real data – the run order

1. **Your bank** – edit `inputs/bank_profile.csv` (year, total assets EUR bn, internal events per cell). No name anywhere.
2. **Events** – `inputs/events_candidates.csv` holds the reviewed FCA fines and the ESMA cases. Change `status` to `include` for the `review` rows you accept (for individuals, fill `employer_bank`).
3. **Optional** – fill sizes in `inputs/banks_manual.csv` for banks with no free source.
4. **Universe** – run
   ```
   py -u build_universe.py --sec-contact "Your Name your@email"
   ```
   It downloads (all free): ECB FX rates, EBA transparency exercise 2017–2025 (EU/EEA banks with LEI and total assets), SEC filings (US, Swiss, UK, Japanese, Canadian banks), GLEIF parent companies. It writes `inputs/peer_panel.csv` (every bank-year, **with and without events**), `inputs/peer_aliases.csv`, `inputs/events.csv`, and `data/universe_report.txt`. Takes a few minutes (the EBA files are large). The SEC asks API users to identify themselves; your contact goes only to the SEC.
5. **Check** `data/events_unmatched.csv` – fines on firms outside the universe (brokers, small banks). If a bank is missing that should be there, add it to `banks_manual.csv` and rerun.
6. Set `DATA_MODE = "REAL"` and `BANK_REGION` in the workbook and run all cells.

To refresh the fines later: `py -u extract_sources.py`, review, update `events_candidates.csv`, rerun step 4.

## Notes on the method
- **Every reported event counts**, including events with unknown amount (ESMA). Probabilities are of a *publicly reported* fine; the workbook shows the amount above which reporting looks complete.
- **The denominator** is every bank-year in the universe within the searched years – banks with zero events count as zeros.
- **Zero-event cells** get a "rare, not impossible" rate (about half an event over the whole sample) through a weak prior, never exactly 0.
- **Frequency** – negative binomial regression on peer bank-years: size elasticity, regime effects (MAD to 2015 / MAR 2016+), region effects (EU, UK, US, OTHER).
- **Bayes** – `θ ~ Gamma(r, r)` scales the external rate to our bank; `r` comes from how much peers differ (or is set by hand). Internal history updates it: `θ | n ~ Gamma(r+n, r+E)`. The sensitivity table shows how much the answer depends on `r`.
- **Severity** – only known amounts; scaled to our size (pooled elasticity), lognormal, pooled across cells when a cell has fewer than 8 amounts, GPD tail when ≥ 15 tail points.
- **Impact** – Monte Carlo including parameter uncertainty; cells summed assuming independence.

## Known limits of the extractor
- The ESMA register only lists **entities** (no individuals) and its coverage is partial: national regulators decide what they report. For MAR/MAD sanctions it holds **no description text, so no amount** – treat it as a list of cases to look up on each national regulator's site.
- FCA reasons are often generic ("breaching Principle 3"), so the classifier also reads the link of each notice (e.g. `...-libor-...`, `...-forex-...`). Every FCA fine, market abuse or not, is saved to `data/fca_all_fines.csv` so nothing relevant is lost silently.
- `penalised_party = bank` means "a firm was fined", not necessarily a bank. Brokers, issuers and exchanges drop out automatically when they are not in your peer list.
- The FCA tables start in 2013; earlier FSA fines must be added by hand.
- Both scrapers depend on the sites' current layout; if a page changes, that year is skipped with a message.
