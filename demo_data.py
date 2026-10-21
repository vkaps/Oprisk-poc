"""
demo_data.py - SYNTHETIC data so the notebook runs end-to-end before real
data is collected. Every row is tagged source='SYNTHETIC_DEMO'.
Numbers are invented; they only have realistic orders of magnitude.
"""
import numpy as np
import pandas as pd

from oprisk_engine import period_of

TRUE = {  # yearly rate for a EUR 300bn EU bank under MAD; amount median / log-sd
    "A1": dict(rate=0.010, med=2e6, sd=1.6),
    "A2": dict(rate=0.030, med=1.2e5, sd=1.5),
    "B1": dict(rate=0.015, med=1e7, sd=2.0),
    "B2": dict(rate=0.020, med=2e5, sd=1.4),
}
PERIOD_MULT = {"pre_MAD": 0.5, "MAD": 1.0, "MAR": 1.6}
REGION_MULT = {"EU": 1.0, "UK": 1.5, "US": 2.0}


def make_demo(seed=7, n_peers=60, years=range(2000, 2026)):
    rng = np.random.default_rng(seed)
    regions = rng.choice(["EU", "UK", "US"], n_peers, p=[0.6, 0.15, 0.25])
    size0 = np.exp(rng.normal(np.log(250), 1.0, n_peers))
    start = rng.choice(list(years)[:12], n_peers)
    panel, notices = [], []
    het = {c: rng.gamma(2.0, 0.5, n_peers) for c in TRUE}  # bank-specific multiplier, mean 1
    nid = 0
    for i in range(n_peers):
        for y in years:
            if y < start[i]:
                continue
            size = size0[i] * 1.03 ** (y - 2000) * np.exp(rng.normal(0, 0.05))
            panel.append(dict(peer_id=f"P{i:03d}", year=y, region=regions[i],
                              total_assets_eur_bn=round(size, 1)))
            for cell, t in TRUE.items():
                lam = (t["rate"] * (size / 300) ** 0.6 * PERIOD_MULT[period_of(y)]
                       * REGION_MULT[regions[i]] * het[cell][i])
                for _ in range(rng.poisson(lam)):
                    amt = np.exp(rng.normal(np.log(t["med"] * (size / 300) ** 0.4), t["sd"]))
                    if rng.random() > min(1.0, (amt / 5e4) ** 0.7):  # small fines go unreported
                        continue
                    nid += 1
                    cid = f"C{nid:05d}"
                    k = 1 + (rng.random() < 0.2) * rng.integers(1, 3) if cell == "B1" else 1
                    for j in range(k):  # same scandal fined by several regulators
                        notices.append(dict(
                            notice_id=f"N{nid:05d}-{j}", cluster_id=cid,
                            date=f"{y}-{rng.integers(1, 13):02d}-15",
                            regulator=["FCA", "SEC", "BaFin", "AMF", "CMVM"][rng.integers(5)],
                            country=regions[i], peer_id=f"P{i:03d}",
                            penalised_party="bank" if cell.endswith("1") else "employee",
                            category="inside_information" if cell[0] == "A" else "market_manipulation",
                            amount_eur=round(amt / k, 0), description="synthetic",
                            source_url="", source="SYNTHETIC_DEMO"))
    return pd.DataFrame(panel), pd.DataFrame(notices)


if __name__ == "__main__":
    p, n = make_demo()
    print(len(p), "bank-years;", len(n), "notices")
