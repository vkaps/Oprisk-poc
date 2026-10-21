"""
build_universe.py - the peer universe (the denominator) and the event list.

Builds, from free sources:
  inputs/fx_rates.csv      ECB annual average FX rates (replaces the approximate defaults)
  inputs/peer_panel.csv    one row per bank group x year, 2013-2025, total assets in EUR bn,
                           INCLUDING banks that never had an event
  inputs/peer_aliases.csv  name patterns per bank group (used to match fines)
  inputs/events.csv        matched events ready for the workbook
  data/events_unmatched.csv  candidates that matched no bank in the universe (review)
  data/universe_report.txt   what came from where

Universe
  * EU/EEA (and UK up to 2020): every bank in the EBA EU-wide transparency
    exercise 2017-2025 (about 120-130 banks per year, LEI + total assets).
  * US, Switzerland, UK after 2020, Japan, Canada: large banks with significant
    UK/EU activity, total assets from their SEC filings (XBRL, free API).
  * Anything else (e.g. Standard Chartered, Nationwide, Australian banks):
    inputs/banks_manual.csv, filled by hand from annual reports.

Run:  python build_universe.py --sec-contact "Your Name your@email"
      (the SEC asks every API user to identify themselves; nothing else is sent)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
INP, DATA = ROOT / "inputs", ROOT / "data"
YEARS = range(2013, 2026)          # complete years covered by FCA (2013+) and ESMA
UA = {"User-Agent": "Mozilla/5.0 (oprisk-poc research script)"}

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
EBA = "https://www.eba.europa.eu"
DL = EBA + "/sites/default/files/document_library/Risk%20Analysis%20and%20Data/EU%20Wide%20Transparency%20Exercise"
EBA_FILES = {  # exercise: (other-templates csv, metadata xlsx)
    2017: (EBA + "/sites/default/files/documents/10180/2027702/acf4b8b4-07d7-40fe-a0b1-7dd067041a71/tr_oth.csv",
           EBA + "/sites/default/files/documents/10180/2027702/61935ee8-4648-40e5-a183-7e0a81b2654c/TR_Metadata.xlsx"),
    2018: (EBA + "/sites/default/files/documents/10180/2518657/85f729ae-90cd-4eb3-ad78-8e87081e157e/tr_oth.csv",
           EBA + "/sites/default/files/documents/10180/2518657/8f6c8589-40e5-4a1b-ad97-a5b9dccd267f/TR_Metadata.xlsx"),
    2019: (DL + "/2019/Full%20database/tr_oth.csv", DL + "/2019/Full%20database/TR_Metadata.xlsx"),
    2020: (EBA + "/sites/default/files/document_library/Risk%20Analysis%20and%20Data/EU%20Wide%20Transparency%20Exercise/2020/Full%20database/885655/tr_oth.csv",
           DL + "/2020/Full%20database/TR_Metadata.xlsx"),
    20202: (DL + "/2020/Autumn%202020/Full%20database/tr_oth_2.csv",
            DL + "/2020/Autumn%202020/Full%20database/TR_Metadata_2.xlsx"),
    2021: (EBA + "/assets/TE2021/Full_database/tr_oth.csv", EBA + "/assets/TE2021/Full_database/TR_Metadata.xlsx"),
    2022: (EBA + "/assets/TE2022/Full_database/tr_oth.csv", EBA + "/assets/TE2022/Full_database/TR_Metadata.xlsx"),
    2023: (EBA + "/assets/TE2023/Full_database/837203/tr_oth.csv", EBA + "/assets/TE2023/Full_database/837203/TR_Metadata.xlsx"),
    2024: (EBA + "/assets/TE2024/Full_database/256109/tr_oth.csv", EBA + "/assets/TE2024/Full_database/256109/TR_Metadata.xlsx"),
    2025: (EBA + "/assets/TE2025/Full_database/883401/tr_oth.csv", EBA + "/assets/TE2025/Full_database/883401/TR_Metadata.xlsx"),
}
ECB_FX = ("https://data-api.ecb.europa.eu/service/data/EXR/A.{ccy}.EUR.SP00.A"
          "?format=csvdata&startPeriod=2000")
FX_CCYS = ["USD", "GBP", "CHF", "JPY", "CAD", "AUD", "SEK", "DKK", "NOK", "PLN", "HUF",
           "CZK", "RON", "BGN", "ISK"]
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
GLEIF_PARENT = "https://api.gleif.org/api/v1/lei-records/{lei}/ultimate-parent"
GLEIF_RECORD = "https://api.gleif.org/api/v1/lei-records/{lei}"
ESMA_SOLR = "https://registers.esma.europa.eu/solr/esma_registers_sanctions/select?q=*:*&rows=10000&wt=json"

# Bank groups: key, display name, country, region, SEC ticker (or CIK), name pattern.
# The pattern merges EBA entries with the same group and matches fine notices.
# Order matters: RBS/NatWest before Lloyds (both contain "bank of scotland").
GROUPS = [
    ("NWG", "NatWest Group", "GB", "UK", "NWG", r"natwest|national westminster|royal bank of scotland|\brbs\b|ulster bank"),
    ("LLOY", "Lloyds Banking Group", "GB", "UK", "LYG", r"lloyds|(?<!royal )bank of scotland|halifax"),
    ("HSBC", "HSBC Holdings", "GB", "UK", "HSBC", r"\bhsbc\b"),
    ("BARC", "Barclays", "GB", "UK", "BCS", r"barclays"),
    ("STAN", "Standard Chartered", "GB", "UK", None, r"standard chartered"),
    ("NBS", "Nationwide Building Society", "GB", "UK", None, r"nationwide building society"),
    ("JPM", "JPMorgan Chase", "US", "US", "JPM", r"j\.? ?p\.? ?morgan|chase bank"),
    ("BAC", "Bank of America", "US", "US", "BAC", r"bank of america|merrill lynch"),
    ("C", "Citigroup", "US", "US", "C", r"\bciti(bank|group|corp)?\b"),
    ("WFC", "Wells Fargo", "US", "US", "WFC", r"wells fargo"),
    ("GS", "Goldman Sachs", "US", "US", "GS", r"goldman sachs"),
    ("MS", "Morgan Stanley", "US", "US", "MS", r"morgan stanley"),
    ("BK", "Bank of New York Mellon", "US", "US", "BK", r"bank of new york|bny mellon"),
    ("STT", "State Street", "US", "US", "STT", r"state street"),
    ("UBS", "UBS Group", "CH", "OTHER", "UBS", r"\bubs\b"),
    ("CS", "Credit Suisse Group", "CH", "OTHER", 1159510, r"credit suisse"),
    ("MUFG", "Mitsubishi UFJ Financial Group", "JP", "OTHER", "MUFG", r"mitsubishi ufj|\bmufg\b"),
    ("MIZ", "Mizuho Financial Group", "JP", "OTHER", "MFG", r"mizuho"),
    ("SMFG", "Sumitomo Mitsui Financial Group", "JP", "OTHER", "SMFG", r"sumitomo mitsui|\bsmbc\b"),
    ("NMR", "Nomura Holdings", "JP", "OTHER", "NMR", r"nomura"),
    ("RY", "Royal Bank of Canada", "CA", "OTHER", "RY", r"royal bank of canada|rbc (capital|europe)"),
    ("TD", "Toronto-Dominion Bank", "CA", "OTHER", "TD", r"toronto.dominion|\btd (bank|securities)"),
    ("BMO", "Bank of Montreal", "CA", "OTHER", "BMO", r"bank of montreal|\bbmo\b"),
    ("BNS", "Bank of Nova Scotia", "CA", "OTHER", "BNS", r"bank of nova scotia|scotiabank"),
    ("CM", "Canadian Imperial Bank of Commerce", "CA", "OTHER", "CM", r"canadian imperial|\bcibc\b"),
    ("MQG", "Macquarie Group", "AU", "OTHER", None, r"macquarie"),
    # EU groups also SEC-listed: EBA is the main source, SEC fills missing years
    ("DB", "Deutsche Bank", "DE", "EU", "DB", r"deutsche bank"),
    ("SAN", "Banco Santander", "ES", "EU", "SAN", r"santander"),
    ("BBVA", "BBVA", "ES", "EU", "BBVA", r"\bbbva\b|bilbao vizcaya"),
    ("ING", "ING Groep", "NL", "EU", "ING", r"\bing (groep|bank)\b"),
    ("RABO", "Rabobank", "NL", "EU", None, r"rabobank|raiffeisen.boerenleenbank"),
]
EEA = set("AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IS IT LI LT LU LV MT NL NO PL PT RO SE SI SK".split())


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def region_of(country: str) -> str:
    c = str(country).upper()[:2]
    return "UK" if c == "GB" else "US" if c == "US" else "EU" if c in EEA else "OTHER"


BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-GB,en;q=0.9"}


class Net:
    def __init__(self, sec_contact: str | None):
        # one line, no control characters (a pasted secret may contain a line break)
        self.sec_contact = " ".join(str(sec_contact).split()) if sec_contact else None

    def get(self, url: str, timeout=90, binary=False, tries=3):
        headers = dict(BROWSER)
        if "sec.gov" in url and self.sec_contact:
            headers = {"User-Agent": f"oprisk-poc {self.sec_contact}", "Accept-Encoding": "identity"}
        last = None
        for i in range(tries):
            try:
                with urlopen(Request(url, headers=headers), timeout=timeout) as r:
                    b = r.read()
                return b if binary else b.decode("utf-8", errors="replace")
            except HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:  # never echo request headers (they hold the contact)
                last = RuntimeError(type(e).__name__)
            time.sleep(5 * (i + 1))
        raise last


def log(msg, report):
    print(msg, flush=True)
    report.append(msg)


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------
def build_fx(net, report) -> pd.DataFrame:
    rows = []
    for ccy in FX_CCYS:
        try:
            df = pd.read_csv(io.StringIO(net.get(ECB_FX.format(ccy=ccy))))
            for _, r in df.iterrows():
                rows.append({"currency": ccy, "year": int(str(r["TIME_PERIOD"])[:4]),
                             "eur_per_unit": 1.0 / float(r["OBS_VALUE"]),
                             "note": "ECB annual average"})
        except Exception as e:
            log(f"  FX {ccy}: failed ({e})", report)
    fx = pd.DataFrame(rows)
    if fx.empty:
        log("  FX: ECB unavailable - keeping existing inputs/fx_rates.csv", report)
        return pd.read_csv(INP / "fx_rates.csv")
    old = pd.read_csv(INP / "fx_rates.csv")
    fx = pd.concat([fx, old[old["year"] == 0]], ignore_index=True)  # keep defaults as fallback
    fx.to_csv(INP / "fx_rates.csv", index=False)
    log(f"  FX: {fx.currency.nunique()} currencies, {fx.year.min()}-{fx.year.max()} from ECB", report)
    return fx


def fx_rate(fx, ccy, year):
    if ccy == "EUR":
        return 1.0
    f = fx[fx["currency"] == ccy]
    if f.empty:
        return np.nan
    exact = f[f["year"] == year]
    if not exact.empty:
        return float(exact["eur_per_unit"].iloc[0])
    real = f[f["year"] > 0]
    if not real.empty:  # nearest year
        return float(real.iloc[(real["year"] - year).abs().argmin()]["eur_per_unit"])
    return float(f["eur_per_unit"].iloc[0])


# ---------------------------------------------------------------------------
# EBA transparency exercise
# ---------------------------------------------------------------------------
def eba_metadata(xlsx: bytes) -> pd.DataFrame:
    """Return LEI, name, country from the metadata workbook (layout varies by year)."""
    out = []
    for _, df in pd.read_excel(io.BytesIO(xlsx), sheet_name=None, header=None).items():
        # find the header row: a row containing an 'LEI' cell
        for i in range(min(len(df), 30)):
            cells = [norm(x) for x in df.iloc[i].tolist()]
            if any("lei" in c for c in cells):
                hdr = cells
                body = df.iloc[i + 1:]
                lei_c = next(j for j, c in enumerate(hdr) if "lei" in c)
                name_c = next((j for j, c in enumerate(hdr) if "name" in c), None)
                ctry_c = next((j for j, c in enumerate(hdr) if c in ("country", "nsa") or "country" in c), None)
                if name_c is None:
                    break
                for _, r in body.iterrows():
                    lei = str(r.iloc[lei_c]).strip()
                    if re.fullmatch(r"[A-Z0-9]{20}", lei):
                        out.append({"lei": lei, "name": str(r.iloc[name_c]).strip(),
                                    "country": str(r.iloc[ctry_c]).strip()[:2] if ctry_c is not None else ""})
                break
    return pd.DataFrame(out).drop_duplicates("lei")


def eba_total_assets(csv_text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text), dtype=str, low_memory=False)
    cols = {c.lower(): c for c in df.columns}
    if "label" not in cols:
        return pd.DataFrame()
    ta = df[df[cols["label"]].str.strip().str.lower() == "total assets"].copy()
    if ta.empty:
        return pd.DataFrame()
    ta["period"] = ta[cols["period"]].astype(str).str[:6]
    ta["amount"] = pd.to_numeric(ta[cols["amount"]], errors="coerce")
    ta = ta.groupby([cols["lei_code"], cols["nsa"], "period"], as_index=False)["amount"].max()
    ta.columns = ["lei", "country", "period", "amount_eur_m"]
    ta["year"] = ta["period"].str[:4].astype(int)
    ta["month"] = ta["period"].str[4:6].astype(int)
    # one value per bank-year: the latest period in that year (December when present)
    ta = ta.sort_values("month").groupby(["lei", "year"], as_index=False).last()
    ta["total_assets_eur_bn"] = ta["amount_eur_m"] / 1000.0
    return ta[["lei", "country", "year", "total_assets_eur_bn"]]


def build_eba(net, report):
    sizes, meta = [], []
    for ex, (csv_url, meta_url) in EBA_FILES.items():
        t0 = time.time()
        try:
            ta = eba_total_assets(net.get(csv_url, timeout=300))
            if ta.empty:
                log(f"  EBA {ex}: no 'Total assets' rows - skipped", report)
            else:
                sizes.append(ta)
                log(f"  EBA {ex}: {ta.lei.nunique()} banks, years {sorted(ta.year.unique())} "
                    f"({time.time()-t0:.0f}s)", report)
        except Exception as e:
            log(f"  EBA {ex}: data failed ({e})", report)
        try:
            meta.append(eba_metadata(net.get(meta_url, binary=True)))
        except Exception as e:
            log(f"  EBA {ex}: metadata failed ({e})", report)
    sizes = pd.concat(sizes, ignore_index=True) if sizes else pd.DataFrame(
        columns=["lei", "country", "year", "total_assets_eur_bn"])
    sizes = sizes.groupby(["lei", "year"], as_index=False).agg(
        country=("country", "first"), total_assets_eur_bn=("total_assets_eur_bn", "max"))
    meta = pd.concat(meta, ignore_index=True).drop_duplicates("lei", keep="last") if meta else \
        pd.DataFrame(columns=["lei", "name", "country"])
    return sizes, meta


# ---------------------------------------------------------------------------
# SEC (US and foreign banks filing 10-K / 20-F / 40-F)
# ---------------------------------------------------------------------------
def sec_assets(facts: dict) -> pd.DataFrame:
    rows = []
    for tax in ("us-gaap", "ifrs-full"):
        node = facts.get("facts", {}).get(tax, {}).get("Assets")
        if not node:
            continue
        for ccy, obs in node.get("units", {}).items():
            for o in obs:
                if o.get("form", "").split("/")[0] in ("10-K", "20-F", "40-F") and o.get("fp") == "FY":
                    rows.append({"end": o["end"], "val": o["val"], "ccy": ccy, "filed": o.get("filed", "")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["end"] = pd.to_datetime(df["end"])
    # fiscal years ending Jan-Mar (Japan, Canada Oct is fine) belong to the previous calendar year
    df["year"] = np.where(df["end"].dt.month <= 3, df["end"].dt.year - 1, df["end"].dt.year)
    return df.sort_values("filed").groupby("year", as_index=False).last()


def build_sec(net, fx, report):
    if not net.sec_contact:
        log("  SEC: skipped (run with --sec-contact \"Name email\")", report)
        return pd.DataFrame()
    try:
        tick = {v["ticker"].upper(): int(v["cik_str"])
                for v in json.loads(net.get(SEC_TICKERS)).values()}
    except Exception as e:
        log(f"  SEC: ticker list failed ({e})", report)
        return pd.DataFrame()
    out = []
    for key, name, ctry, reg, sec, _ in GROUPS:
        if sec is None:
            continue
        cik = sec if isinstance(sec, int) else tick.get(sec)
        if not cik:
            log(f"  SEC {key}: ticker {sec} not found", report)
            continue
        try:
            a = sec_assets(json.loads(net.get(SEC_FACTS.format(cik=cik))))
            time.sleep(0.2)  # SEC fair-access limit
        except Exception as e:
            log(f"  SEC {key}: failed ({e})", report)
            continue
        if a.empty:
            log(f"  SEC {key}: no XBRL total assets", report)
            continue
        a["total_assets_eur_bn"] = [v * fx_rate(fx, c, y) / 1e9 for v, c, y in zip(a["val"], a["ccy"], a["year"])]
        a["group_key"] = key
        out.append(a[["group_key", "year", "total_assets_eur_bn"]])
        log(f"  SEC {key}: {a.year.min()}-{a.year.max()}", report)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ---------------------------------------------------------------------------
# Universe assembly
# ---------------------------------------------------------------------------
def group_for_name(name: str) -> str | None:
    t = norm(name)
    for key, *_, pat in GROUPS:
        if re.search(pat, t):
            return key
    return None


def assemble(eba_sizes, eba_meta, sec, manual, report) -> tuple[pd.DataFrame, pd.DataFrame]:
    banks = {}  # group_key -> dict(name, country, region, leis)
    obs = []
    for key, name, ctry, reg, *_ in GROUPS:
        banks[key] = {"group_key": key, "name": name, "country": ctry, "region": reg, "leis": set()}
    name_of = dict(zip(eba_meta["lei"], eba_meta["name"]))
    for lei, g in eba_sizes.groupby("lei"):
        nm = name_of.get(lei, lei)
        key = group_for_name(nm) or f"EBA_{lei}"
        ctry = str(g["country"].iloc[0])
        b = banks.setdefault(key, {"group_key": key, "name": nm, "country": ctry,
                                   "region": region_of(ctry), "leis": set()})
        b["leis"].add(lei)
        for _, r in g.iterrows():
            obs.append({"group_key": key, "year": r.year, "total_assets_eur_bn": r.total_assets_eur_bn, "src": "EBA"})
    for _, r in sec.iterrows():
        obs.append({"group_key": r.group_key, "year": r.year, "total_assets_eur_bn": r.total_assets_eur_bn, "src": "SEC"})
    for _, r in manual.dropna(subset=["total_assets_eur_bn"]).iterrows():
        key = r.group_key
        banks.setdefault(key, {"group_key": key, "name": r["name"], "country": r.country,
                               "region": region_of(r.country), "leis": set()})
        obs.append({"group_key": key, "year": int(r.year), "total_assets_eur_bn": float(r.total_assets_eur_bn), "src": "manual"})
    obs = pd.DataFrame(obs)
    if obs.empty:
        raise SystemExit("No bank sizes from any source - check the log above.")
    # EU groups: EBA first (group level). Non-EU groups: SEC first, because the EBA
    # files only hold their EU subsidiaries (e.g. "J.P. Morgan SE").
    reg = {k: b["region"] for k, b in banks.items()}
    obs["p"] = [({"EBA": 0, "manual": 1, "SEC": 2} if reg.get(k) == "EU" else
                 {"SEC": 0, "manual": 1, "EBA": 2})[s] for k, s in zip(obs["group_key"], obs["src"])]
    obs = obs.sort_values("p").groupby(["group_key", "year"], as_index=False).first()

    # panel: backfill to 2013 with the earliest observed size; forward-fill at most 1 year
    rows = []
    for key, g in obs.groupby("group_key"):
        g = g.set_index("year")
        first, last = g.index.min(), g.index.max()
        for y in YEARS:
            if y > last + 1:
                continue  # group gone (merged / failed) or no data yet
            if y in g.index:
                size, src, imp = g.loc[y, "total_assets_eur_bn"], g.loc[y, "src"], False
            else:
                ref = first if y < first else last
                size, src, imp = g.loc[ref, "total_assets_eur_bn"], g.loc[ref, "src"], True
            b = banks[key]
            rows.append({"peer_id": key, "peer_name": b["name"], "country": b["country"],
                         "region": b["region"], "year": y, "total_assets_eur_bn": round(float(size), 2),
                         "size_source": src, "size_imputed": imp})
    panel = pd.DataFrame(rows)
    bank_tbl = pd.DataFrame([{**b, "leis": ";".join(sorted(b["leis"]))} for b in banks.values()
                             if b["group_key"] in set(panel.peer_id)])
    log(f"\nUniverse: {panel.peer_id.nunique()} bank groups, {len(panel)} bank-years "
        f"({panel.size_imputed.mean():.0%} of sizes imputed from nearest year)", report)
    log(panel.groupby("region").peer_id.nunique().rename("banks").to_string(), report)
    return panel, bank_tbl


def write_aliases(bank_tbl: pd.DataFrame):
    pats = {k: p for k, *_, p in GROUPS}
    rows = []
    for _, b in bank_tbl.iterrows():
        pat = pats.get(b.group_key)
        if not pat:  # EBA-only bank: pattern from its name without legal suffixes
            core = re.sub(r"\b(ag|sa|s\.a\.|spa|s\.p\.a\.|plc|nv|n\.v\.|se|group|groupe|gruppe|holding|"
                          r"aktiengesellschaft|a/s|asa|abp|oyj|ab|d\.d\.|a\.s\.|zrt|nyrt|the)\b\.?", " ", norm(b["name"]))
            core = re.sub(r"[^a-z0-9 ]", " ", core).split()
            pat = r"\b" + r"\s+".join(map(re.escape, core[:3])) + r"\b" if core else None
        if pat:
            rows.append({"peer_id": b.group_key, "alias_regex": pat})
    pd.DataFrame(rows).to_csv(INP / "peer_aliases.csv", index=False)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Event matching
# ---------------------------------------------------------------------------
def gleif_parent(net, lei: str, cache: dict) -> tuple[str, str]:
    """Ultimate parent (LEI, name) from GLEIF; the entity itself if none is reported."""
    if lei in cache:
        return tuple(cache[lei])
    try:
        d = json.loads(net.get(GLEIF_PARENT.format(lei=lei), timeout=30))["data"]
        res = (d["id"], d["attributes"]["entity"]["legalName"]["name"])
    except HTTPError as e:
        if e.code != 404:
            return lei, ""
        try:  # no parent reported: use the entity's own name
            d = json.loads(net.get(GLEIF_RECORD.format(lei=lei), timeout=30))["data"]
            res = (lei, d["attributes"]["entity"]["legalName"]["name"])
        except Exception:
            res = (lei, "")
    except Exception:
        return lei, ""
    cache[lei] = list(res)
    time.sleep(0.1)
    return res


def match_events(net, cands, bank_tbl, aliases, report):
    lei_to_key = {l: r.group_key for _, r in bank_tbl.iterrows() for l in str(r.leis).split(";") if l}
    cache_f = DATA / "gleif_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}

    # ESMA candidates: fetch entity LEIs from the register if missing
    esma = cands["source"].eq("ESMA") & cands["entity_lei"].isna()
    if esma.any():
        try:
            docs = json.loads(net.get(ESMA_SOLR, timeout=120))["response"]["docs"]
            m = {f"ESMA-{d.get('sn_sanctionEsmaID')}": d.get("sn_entityLEI") for d in docs}
            cands.loc[esma, "entity_lei"] = cands.loc[esma, "notice_id"].map(m)
        except Exception as e:
            log(f"  ESMA LEI lookup failed ({e}) - matching ESMA by name only", report)

    def by_name(*names):
        for nm in names:
            t = norm(nm)
            if not t:
                continue
            for _, a in aliases.iterrows():
                if re.search(a.alias_regex, t):
                    return a.peer_id
        return None

    peer, how, parent_names = [], [], []
    for _, c in cands.iterrows():
        pid, h, pname = None, "", ""
        emp = c.get("employer_bank")
        if isinstance(emp, str) and emp.strip():            # fined individual -> employer
            pid, h = by_name(emp), "employer"
        if pid is None and isinstance(c.get("entity_lei"), str) and len(c["entity_lei"]) == 20:
            plei, pname = gleif_parent(net, c["entity_lei"], cache)
            pid = lei_to_key.get(c["entity_lei"]) or lei_to_key.get(plei)
            h = "LEI" if pid else ""
            if pid is None:
                pid = by_name(c["entity_name"], pname)
                h = "name+GLEIF parent" if pid else ""
        if pid is None and c["penalised_party"] == "bank":
            pid, h = by_name(c["entity_name"]), "name"
        peer.append(pid); how.append(h if pid else ""); parent_names.append(pname)
    cache_f.write_text(json.dumps(cache))
    cands = cands.assign(peer_id=peer, matched_by=how, gleif_parent_name=parent_names)
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec-contact", default="", help='e.g. "Jane Doe jane@example.com"')
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    net, report = Net(args.sec_contact or None), []

    log("1/5 FX rates (ECB) ...", report)
    fx = build_fx(net, report)
    log("2/5 EBA transparency exercise (EU/EEA banks) ...", report)
    eba_sizes, eba_meta = build_eba(net, report)
    log("3/5 SEC filings (US, CH, JP, CA, UK and EU ADRs) ...", report)
    sec = build_sec(net, fx, report)
    manual = pd.read_csv(INP / "banks_manual.csv")
    log("4/5 Assembling universe ...", report)
    panel, bank_tbl = assemble(eba_sizes, eba_meta, sec, manual, report)
    panel.to_csv(INP / "peer_panel.csv", index=False)
    bank_tbl.to_csv(DATA / "universe_banks.csv", index=False)
    aliases = write_aliases(bank_tbl)

    log("5/5 Matching events to the universe ...", report)
    cands = pd.read_csv(INP / "events_candidates.csv", dtype={"entity_lei": str, "employer_bank": str})
    cands = cands[cands["status"] == "include"].copy()
    m = match_events(net, cands, bank_tbl, aliases, report)
    ok, bad = m[m.peer_id.notna()], m[m.peer_id.isna()]
    cols = ["notice_id", "cluster_id", "date", "regulator", "country", "peer_id", "penalised_party",
            "category", "amount_eur", "description", "source_url", "source"]
    ok[cols].to_csv(INP / "events.csv", index=False)
    bad.to_csv(DATA / "events_unmatched.csv", index=False)
    m.to_csv(DATA / "events_matching_detail.csv", index=False)
    log(f"  {len(ok)} events matched to a universe bank, {len(bad)} not in the universe "
        f"(see data/events_unmatched.csv)", report)
    zero = panel.peer_id.nunique() - ok.peer_id.nunique()
    log(f"  {zero} of {panel.peer_id.nunique()} banks have no event: they are the non-events", report)
    (DATA / "universe_report.txt").write_text("\n".join(report))
    print("\nDone. Open the workbook with DATA_MODE = 'REAL'.")


if __name__ == "__main__":
    main()
