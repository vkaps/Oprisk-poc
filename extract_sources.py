"""
extract_sources.py - pull free public enforcement data and pre-classify it.

Sources automated here
  * ESMA sanctions register (MAR / MAD sanctions reported by EU national
    regulators). Public Solr endpoint used by ESMA's own register website.
  * FCA yearly fines tables, 2013 -> current year.

Sources to add by hand (no stable machine-readable feed; see README):
  FSA fines 2000-2012, SEC/CFTC litigation releases, CMVM, Banco de Portugal,
  AMF, BaFin, CONSOB, CNMV ... Enter them in inputs/events_manual.csv.

Output: data/events_raw.csv - one row per sanction notice, with a suggested
category (inside_information / market_manipulation), penalised party, amount
in EUR and a suggested peer_id. NOTHING is final until you review it:
copy the rows you accept into inputs/events.csv.

Run:  python extract_sources.py            (both sources)
      python extract_sources.py --only fca
"""
from __future__ import annotations

import argparse
import time
import html
import json
import re
import unicodedata
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (oprisk-poc research script)"}

ESMA_SOLR = "https://registers.esma.europa.eu/solr/esma_registers_sanctions/select"
FCA_YEAR_URL = "https://www.fca.org.uk/news/news-stories/{year}-fines"


def fetch(url: str, timeout: int = 30) -> str:
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Classification (multilingual keywords; accents removed before matching)
# ---------------------------------------------------------------------------
def norm(s: str) -> str:
    s = str(s or "").replace("€", " eur ").replace("£", " gbp ").replace("$", " usd ")
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower())


# Regex rules on normalised text (reason + entity name + URL slug, because FCA
# reasons are often generic, e.g. "Principle 3", while the link says "libor").
INSIDE = [
    r"insider (dealing|trading|lists?)", r"inside information", r"unlawful(ly)? disclos",
    r"suspicious (client )?(transactions?|orders?)", r"\bstors?\b", r"information barriers?",
    r"chinese walls?", r"closed periods?", r"\bpdmrs?\b", r"article (8|10|14|16|17|18|19)\b",
    r"\b1[46]\([a-c0-9]\)", r"(s|section) ?118 ?\((2|3|4)\)", r"misuse of information",
    r"informacao privilegiada", r"abuso de informacao", r"informacion privilegiada",
    r"lista de (iniciados|pessoas)", r"operaciones sospechosas", r"information privilegiee",
    r"d'initie", r"informazioni privilegiate", r"abuso di informazioni",
    r"insider ?(information|handel|verzeichnis|liste)", r"\binsider\b",
]
MANIP = [
    r"manipul\w*", r"spoofing", r"layering", r"wash trad", r"marking the close",
    r"benchmark", r"\b\w*ibor\b", r"\bfx\b", r"forex", r"foreign exchange",
    r"gold fix", r"\bfixings?\b", r"article (12|15)\b", r"(s|section) ?118 ?\((5|6|7|8)\)",
    r"false or misleading (impression|signals?)", r"marktmanipulation",
]
GENERIC = [r"market abuse", r"abuso de mercado", r"abus de marche", r"abusi di mercato",
           r"marktmissbrauch", r"market abuse regulation"]


def classify(text: str) -> tuple[str | None, str]:
    """Return (category, confidence). STOR / insider-list / information-barrier
    failures go to inside_information, as agreed in the spec."""
    t = norm(text.replace("-", " ").replace("_", " "))
    hi = sum(bool(re.search(p, t)) for p in INSIDE)
    hm = sum(bool(re.search(p, t)) for p in MANIP)
    if hi == 0 and hm == 0:
        return (None, "none") if not any(re.search(p, t) for p in GENERIC) \
            else ("market_abuse_unspecified", "low")
    if hi and hm:
        return ("inside_information" if hi > hm else "market_manipulation"), "low"
    return ("inside_information" if hi else "market_manipulation"), "medium"


FIRM_RE = re.compile(
    r"\b(ltd|limited|plc|llp|llc|inc|ag|sa|s\.a\.|spa|s\.p\.a\.|gmbh|nv|n\.v\.|n\.a\.|b\.a\.|"
    r"bv|se|lp|uc|group|securities|capital|partners|markets|brokers?|broking|exchange|"
    r"asset management|investments?|international|& co|company|corp|trust|\(rie\))\b"
    r"|bank|banco|banque|financ", re.I)


def party_of(name: str) -> str:
    return "bank" if FIRM_RE.search(norm(name)) else "employee"


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------
def load_fx() -> pd.DataFrame:
    return pd.read_csv(ROOT / "inputs" / "fx_rates.csv")


def to_eur(amount: float, ccy: str, year: int, fx: pd.DataFrame) -> float | None:
    if amount is None or ccy is None:
        return None
    if ccy == "EUR":
        return amount
    f = fx[fx["currency"] == ccy]
    if f.empty:
        return None
    exact = f[f["year"] == year]
    rate = (exact if not exact.empty else f[f["year"] == 0])["eur_per_unit"]
    return amount * float(rate.iloc[0]) if len(rate) else None


CCY = {"eur": "EUR", "euro": "EUR", "euros": "EUR", "gbp": "GBP",
       "usd": "USD", "czk": "CZK", "pln": "PLN", "sek": "SEK", "dkk": "DKK",
       "huf": "HUF", "ron": "RON", "bgn": "BGN", "nok": "NOK", "chf": "CHF", "isk": "ISK",
       "hrk": "HRK", "kc": "CZK", "zl": "PLN", "lei": "RON", "kr": "SEK"}
MULT = {"million": 1e6, "millions": 1e6, "milhoes": 1e6, "milhao": 1e6, "millones": 1e6,
        "millon": 1e6, "milioni": 1e6, "milione": 1e6, "mio": 1e6, "mln": 1e6, "m": 1e6,
        "thousand": 1e3, "mil": 1e3, "k": 1e3, "billion": 1e9, "bn": 1e9}
NUM = r"\d{1,3}(?:[.,\s']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
CCY_WORDS = r"eur|euros?|gbp|usd|czk|pln|sek|dkk|huf|ron|bgn|nok|chf|isk|hrk|kc|zl|lei|kr"
MULT_WORDS = (r"millions?|milhoes|milhao|millones|millon|milioni|milione|mio\.?|mln|"
              r"billion|bn|thousand|mil|k|m")
AMOUNT_RE = re.compile(
    rf"\b(?P<c1>{CCY_WORDS})\s*(?P<n1>{NUM})\s*(?P<m1>{MULT_WORDS})?(?![a-z])"
    rf"|(?P<n2>{NUM})\s*(?P<m2>{MULT_WORDS})?\s*(?:de |d'|of )?(?P<c2>{CCY_WORDS})\b")


def parse_number(s: str) -> float:
    s = s.replace(" ", " ").replace("'", "").strip()
    if re.fullmatch(r"\d{1,3}([.,\s]\d{3})+", s):          # pure thousands groups
        return float(re.sub(r"[.,\s]", "", s))
    m = re.fullmatch(r"(\d{1,3}(?:[.,\s]\d{3})+)([.,])(\d{1,2})", s)
    if m:                                                    # groups + decimals
        return float(re.sub(r"[.,\s]", "", m.group(1)) + "." + m.group(3))
    return float(s.replace(",", "."))


def extract_amount(text: str) -> tuple[float | None, str | None]:
    """Largest monetary amount in the text (fines usually dominate other figures)."""
    best = (None, None)
    for m in AMOUNT_RE.finditer(norm(text)):
        n = m.group("n1") or m.group("n2")
        c = (m.group("c1") or m.group("c2") or "").lower()
        mult = (m.group("m1") or m.group("m2") or "").lower().rstrip(".")
        try:
            v = parse_number(n) * MULT.get(mult, 1.0)
        except ValueError:
            continue
        ccy = CCY.get(c, c.upper() or None)
        if best[0] is None or v > best[0]:
            best = (v, ccy)
    return best


# ---------------------------------------------------------------------------
# Peer matching
# ---------------------------------------------------------------------------
def match_peer(name: str, aliases: pd.DataFrame) -> str | None:
    t = norm(name)
    for _, a in aliases.iterrows():
        if re.search(str(a["alias_regex"]).lower(), t):
            return a["peer_id"]
    return None


def load_aliases() -> pd.DataFrame:
    p = ROOT / "inputs" / "peer_aliases.csv"   # written by build_universe.py
    return pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["peer_id", "alias_regex"])


# ---------------------------------------------------------------------------
# ESMA sanctions register
# ---------------------------------------------------------------------------
def extract_esma(fx, aliases) -> pd.DataFrame:
    t0 = time.time()
    url = f"{ESMA_SOLR}?q=*:*&rows=10000&wt=json"
    docs = json.loads(fetch(url, timeout=120))["response"]["docs"]
    print(f"  {len(docs)} sanctions downloaded ({time.time()-t0:.0f}s)", flush=True)
    rows = []
    for d in docs:
        fw = str(d.get("sn_sanctionLegalFrameworkName", ""))
        if fw not in ("MAR", "MAD"):
            continue
        name = re.sub(r"<[^>]+>", "", html.unescape(str(d.get("sn_entityName", "")))).strip()
        text = str(d.get("sn_text", ""))
        dt = str(d.get("sn_date", ""))[:10]
        yr = int(dt[:4]) if dt[:4].isdigit() else None
        cat, conf = classify(text)
        amt, ccy = extract_amount(text)
        rows.append(dict(
            notice_id=f"ESMA-{d.get('sn_sanctionEsmaID')}", cluster_id="", date=dt,
            regulator=d.get("sn_ncaCodeFullName"), country=d.get("sn_countryName"),
            entity_name=name, entity_lei=d.get("sn_entityLEI"), peer_id=match_peer(name, aliases),
            penalised_party="bank",  # register lists entities (firms)
            category=cat, class_confidence=conf, legal_framework=fw,
            amount_orig=amt, currency=ccy, amount_eur=to_eur(amt, ccy, yr, fx),
            description=(re.sub(r"\s+", " ", text)[:600] or
                         "No text in ESMA register - look up amount and reason on the "
                         "national regulator's site"),
            source_url=ESMA_SOLR, source="ESMA"))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# FCA yearly fines tables
# ---------------------------------------------------------------------------
class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in_cell, self._href = [], None, [], False, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._in_cell, self._cell, self._href = True, [], None
        elif tag == "a" and self._in_cell and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._in_cell:
            self._row.append((re.sub(r"\s+", " ", "".join(self._cell)).strip(), self._href))
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def parse_fca_page(page: str, year: int, fx, aliases) -> list[dict]:
    p = _TableParser()
    p.feed(page)
    out = []
    for r in p.rows:
        if len(r) < 4 or not re.search(r"\d{2}/\d{2}/\d{4}", r[1][0]):
            continue
        name, href = r[0]
        d, m, y = re.search(r"(\d{2})/(\d{2})/(\d{4})", r[1][0]).groups()
        reason = r[3][0]
        if href and href.startswith("/"):
            href = "https://www.fca.org.uk" + href
        slug = (href or "").rstrip("/").rsplit("/", 1)[-1]
        cat, conf = classify(f"{reason} {name} {slug}")
        amt_txt = r[2][0].replace(",", "")
        mnum = re.search(r"[\d.]+", amt_txt)
        amt = float(mnum.group()) if mnum else None
        party = party_of(name)
        out.append(dict(
            notice_id=f"FCA-{y}{m}{d}-{re.sub(r'[^A-Za-z]', '', name)[:20]}", cluster_id="",
            date=f"{y}-{m}-{d}", regulator="FCA", country="UNITED KINGDOM",
            entity_name=name, peer_id=match_peer(name, aliases) if party == "bank" else None,
            penalised_party=party, category=cat, class_confidence=conf,
            legal_framework="", amount_orig=amt, currency="GBP",
            amount_eur=to_eur(amt, "GBP", int(y), fx),
            description=reason[:600], source_url=href or FCA_YEAR_URL.format(year=year),
            source="FCA"))
    return out


def extract_fca(fx, aliases, first_year=2013) -> pd.DataFrame:
    """Returns ALL fines (also saved to data/fca_all_fines.csv for audit);
    the market-abuse subset is selected in main()."""
    rows = []
    for yr in range(first_year, date.today().year + 1):
        t0 = time.time()
        try:
            got = parse_fca_page(fetch(FCA_YEAR_URL.format(year=yr)), yr, fx, aliases)
            rows += got
            n_ma = sum(r["category"] is not None for r in got)
            print(f"  FCA {yr}: {len(got)} fines, {n_ma} market abuse ({time.time()-t0:.0f}s)",
                  flush=True)
        except Exception as e:  # page missing / layout change / timeout
            print(f"  FCA {yr}: skipped after {time.time()-t0:.0f}s ({e})", flush=True)
    df = pd.DataFrame(rows)
    (ROOT / "data").mkdir(exist_ok=True)
    df.to_csv(ROOT / "data" / "fca_all_fines.csv", index=False)
    return df[df["category"].notna()] if len(df) else df


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["esma", "fca"])
    args = ap.parse_args()
    fx, aliases = load_fx(), load_aliases()
    frames = []
    if args.only in (None, "esma"):
        print("ESMA sanctions register ...", flush=True)
        frames.append(extract_esma(fx, aliases))
    if args.only in (None, "fca"):
        print("FCA fines tables ...", flush=True)
        frames.append(extract_fca(fx, aliases))
    raw = pd.concat(frames, ignore_index=True)
    raw["needs_review"] = (raw["class_confidence"] != "medium") | raw["peer_id"].isna() \
        | raw["amount_eur"].isna()
    (ROOT / "data").mkdir(exist_ok=True)
    out = ROOT / "data" / "events_raw.csv"
    raw.to_csv(out, index=False)
    print(f"\n{len(raw)} market-abuse notices written to {out}")
    print(raw.groupby(["source", "category"]).size().to_string())


if __name__ == "__main__":
    main()
