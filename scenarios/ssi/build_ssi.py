"""Losses caused by wrong standing settlement instructions (SSIs): honest errors and
fraudulent changes of payee bank details. Builds the event list and a frequency-severity
estimate of the annual probability for one bank's market-operations payments.

Run: python scenarios/ssi/build_ssi.py  ->  ssi_events.csv, ssi_model.json
"""
import csv
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent

# ---------------------------------------------------------------- events
# (id, announced, firm, sector, country, type, how, gross_usd_m, net_usd_m, recovered_note, ssi_fit, source1, source2, confidence)
EVENTS = [
    ("SSI01", "2017-03", "Facebook and Google (Rimasauskas)", "Corporate", "US", "Fake payee bank details",
     "A fraudster set up a company named like a real supplier (Quanta), sent invoices and fake 'bank letters' telling staff to pay his accounts in Latvia and Cyprus, 2013-2015.",
     122.0, None, "Most recovered; USD 50m forfeited", "High",
     "https://www.theregister.com/2019/03/21/facebook_google_scam/", "", "High"),
    ("SSI02", "2017-12", "Japan Airlines", "Corporate", "Japan", "Counterparty SSI change",
     "Emails posing as the US aircraft lessor and a logistics provider asked JAL to pay lease and commission payments to new Hong Kong accounts instead of the usual US accounts.",
     3.4, 3.4, "Not recovered (reported)", "High",
     "https://thepaypers.com/fraud-and-fincrime/news/japan-airlines-pays-out-usd-34-million-to-hong-kong-accounts-in-bank-transfer-scam", "", "High"),
    ("SSI03", "2018-10", "Tecnimont Arabia", "Corporate treasury", "Saudi Arabia/UK", "Counterparty SSI change",
     "From a hacked mailbox of the lender's finance director, an email said the usual bank details were 'under review' and gave a new NatWest account; a USD 5m loan repayment was paid and moved out within days.",
     5.0, 4.36, "About USD 0.64m recovered; claim against the receiving bank failed", "High",
     "https://caselaw.nationalarchives.gov.uk/ewhc/comm/2022/1172", "", "High"),
    ("SSI04", "2019-08", "Toyota Boshoku (European subsidiary)", "Corporate", "Europe", "False payment instructions",
     "A third party's false payment instructions led to an outflow of up to JPY 4bn; reported in the press as a change of account information.",
     36.7, 36.7, "Recovery attempted; maximum loss stated", "Medium",
     "https://www2.jpx.co.jp/disc/31160/140120190906495579.pdf", "https://thepaypers.com/payments/news/toyota-boshoku-subsidiary-loses-over-usd-37-million-in-bec-fraud", "Medium"),
    ("SSI05", "2020-01", "Puerto Rico Industrial Development Company", "Public sector", "US", "Counterparty SSI change",
     "An email said the bank account for remittance payments had changed; USD 2.6m was sent to the fraudster's account.",
     2.6, 2.6, "Partly frozen (not quantified)", "High",
     "https://www.pbs.org/newshour/nation/official-says-puerto-rico-government-lost-2-6m-in-phishing-scam", "", "High"),
    ("SSI06", "2020-03", "Norfund (Norwegian development fund)", "Investment fund", "Norway", "Counterparty SSI change",
     "Fraudsters intercepted emails with a Cambodian borrower and changed the payment details of a USD 10m loan disbursement to an account with the borrower's name but not its owner; found six weeks later.",
     10.0, 10.0, "Not recovered (reported)", "High",
     "https://www.norfund.no/norfund-has-been-exposed-to-a-serious-case-of-fraud/", "", "High"),
    ("SSI07", "2020-09", "Levitas Capital (via fund administrator)", "Investment fund", "Australia", "Fake payee bank details",
     "After a fake Zoom invite gave access to email, USD 8.7m of fake invoices to previously unused accounts were approved by the administrator on spoofed email approval; most transfers were stopped.",
     8.7, 0.8, "About USD 7.9m stopped", "High",
     "https://www.acaglobal.com/industry-insights/zoom-scam-forces-closure-australian-hedge-fund/", "", "High"),
    ("SSI08", "2025-07", "NTMA / Ireland Strategic Investment Fund", "Investment fund", "Ireland", "Counterparty SSI change",
     "A payment request imitating an existing investee company (a capital call) was paid to the fraudster; NTMA controls did not stop it.",
     5.65, 2.83, "EUR 2.5m of EUR 5m recovered", "High",
     "https://www.irishexaminer.com/business/economy/arid-41917936.html", "https://www.irishtimes.com/crime-law/2025/07/12/up-to-5m-goes-missing-after-ntma-falls-victim-to-phishing-scam/", "High"),
]

# Industry base rates used by the model
BASE = {
    "swift_ssi_errors_per_year": 40e6, "swift_ssi_error_cost_usd": 700e6, "swift_year": 2011,
    "dtcc_share_fails_ssi": 0.20,
    "ic3_bec_complaints_2024": 21442, "ic3_bec_losses_2024_usd": 2.77e9,
    "moore_success_rate": 0.525, "moore_share_success_over_1m": 0.014, "moore_dollar_share_over_1m": 0.31,
    "afp_2025_bec_targeted": 0.74, "afp_2025_loss_rev_over_1bn": 0.66,
    "uk_invoice_mandate_cases_2024": 5759, "uk_invoice_mandate_losses_2024_gbp": 42.7e6,
}

# ---------------------------------------------------------------- model
# Prior for a large payer with email-based payee changes (corporate accounts payable):
#   US BEC losses >= USD 1m per year = complaints x success x share>1m / reporting rate
#   x share that are payee-detail redirection, divided by organisations making such payments.
ASSUMPTIONS = {
    "reporting_rate": (0.3, 0.5, 0.7),        # share of >=1m BEC losses reported to IC3 (low, central, high)
    "redirect_share": (0.4, 0.5, 0.6),        # share of BEC that is payee/bank-detail redirection (vs CEO fraud)
    "large_payers": (60000, 40000, 25000),    # US organisations routinely paying >= USD 1m (high count -> low rate)
    "bank_control_factor": (0.05, 0.2, 0.5),  # bank market ops vs corporate AP: SWIFT/directories, call-back, 4-eyes
    "pareto_alpha": (1.0, 0.8, 0.6),          # tail above USD 1m (higher alpha = thinner tail)
    "recovery_mean": 0.3,
    "error_upper": 0.0001,                    # honest-SSI-error loss >= 1m per bank-year (rule of three, see notes)
}


def corporate_rate(i):
    a = ASSUMPTIONS
    n_ge1m = BASE["ic3_bec_complaints_2024"] * BASE["moore_success_rate"] * BASE["moore_share_success_over_1m"]
    return n_ge1m / a["reporting_rate"][i] * a["redirect_share"][i] / a["large_payers"][i], n_ge1m


def hill_alpha():
    xs = [e[8] for e in EVENTS if e[8] and e[8] >= 1.0]
    return len(xs) / sum(math.log(x) for x in xs), xs


def simulate(lam, alpha, cap_m, recov, years=400000, seed=7):
    rng = np.random.default_rng(seed)
    n = rng.poisson(lam, years)
    tot = n.sum()
    sev = (1.0 - rng.random(tot)) ** (-1 / alpha)          # Pareto gross amount, xmin = USD 1m
    sev = np.minimum(sev, cap_m)
    sev *= 1 - rng.beta(1.0, (1 - recov) / recov, tot)      # recovered share, mean = recov
    idx = np.repeat(np.arange(years), n)
    loss = np.bincount(idx, weights=sev, minlength=years)
    big = np.bincount(idx, weights=(sev >= 10).astype(float), minlength=years)
    return {"p_any_1m_gross": float((n > 0).mean()), "p_net_ge_1m": float((loss >= 1).mean()),
            "p_net_ge_10m": float((big > 0).mean()), "expected_loss_m": float(loss.mean()),
            "q99_m": float(np.quantile(loss, 0.99)), "q999_m": float(np.quantile(loss, 0.999))}


def main():
    with open(HERE / "ssi_events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "announced", "firm", "sector", "country", "ssi_type", "what_happened", "gross_usd_m",
                    "net_loss_usd_m", "recovery", "fit", "source_1", "source_2", "confidence"])
        w.writerows(EVENTS)
    a_hill, xs = hill_alpha()
    scen = {}
    for i, name in enumerate(["low", "central", "high"]):
        corp, n_ge1m = corporate_rate(i)
        lam_f = corp * ASSUMPTIONS["bank_control_factor"][i]
        lam = lam_f + ASSUMPTIONS["error_upper"] * (0.5 if i == 1 else (0.1 if i == 0 else 1))
        alpha = ASSUMPTIONS["pareto_alpha"][i]
        sim = simulate(lam, alpha, 100.0, ASSUMPTIONS["recovery_mean"])
        scen[name] = {"corporate_rate": corp, "bank_rate_fraud": lam_f, "lambda": lam, "alpha": alpha, **sim,
                      "return_period_net_1m": 1 / sim["p_net_ge_1m"] if sim["p_net_ge_1m"] else None,
                      "return_period_net_10m": 1 / sim["p_net_ge_10m"] if sim["p_net_ge_10m"] else None}
        print(name, {k: (round(v, 6) if isinstance(v, float) else v) for k, v in scen[name].items()})
    print("US >=1m BEC losses reported per year:", round(n_ge1m), "| Hill alpha from public events:", round(a_hill, 2), xs)
    out = {"events": [dict(zip(["event_id", "announced", "firm", "sector", "country", "ssi_type", "what_happened", "gross_usd_m",
                                 "net_loss_usd_m", "recovery", "fit", "source_1", "source_2", "confidence"], e)) for e in EVENTS],
           "base": BASE, "assumptions": ASSUMPTIONS, "scenarios": scen, "hill_alpha_public": a_hill,
           "us_ge1m_reported": n_ge1m}
    (HERE / "ssi_model.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
