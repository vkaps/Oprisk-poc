"""Market-operations back-office view of the Extreme Loss Library.

Selects the events where an internal validation in a market-operations back office
(treasury / capital-markets operations) failed or would have caught the loss, and tags
each with product, process step and the validation that failed.

relevance: "core"   = the product or process is run by a market-ops back office
           "analog" = another product (futures, commodities, ABS), same validation failure
Output: market_ops_bo.csv / .json (events) and market_ops_steps.json (scenario prompts).
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
FX, FXO, IRD, STR, MM, PAY, SEC, OTH = ("FX spot, forwards & swaps", "FX options",
                                        "Interest rate derivatives (swaps, swaptions, caps, floors)",
                                        "Structured products", "Money markets, deposits & loans",
                                        "Interbank transfers & nostro", "Repo, securities & collateral",
                                        "Other traded products (analog)")
CAP, CONF, SETT, NOST, IPV, COLL, CHG, MSG, REP = ("Trade capture & booking validation", "Confirmation & matching",
                                                  "Payment release & settlement", "Nostro & cash reconciliation",
                                                  "Independent price verification", "Collateral & margin",
                                                  "System change & static data", "Payment message security",
                                                  "Regulatory trade reporting")

# id: (product, process step, validation that failed, relevance)
TAGS = {
    "PS01": (MM, SETT, "Manual override in the loan system paid out principal instead of an interest payment; three approvers passed the screen.", "core"),
    "PS02": (FX, SETT, "A junior FX operations clerk sent the gross instead of the net amount of a trade; the four-eye check was missing.", "core"),
    "PS03": (SEC, COLL, "Routine collateral transfer to a clearing house sent with the wrong amount (EUR 28bn); recalled.", "core"),
    "PS04": (PAY, SETT, "Amount entered with extra zeros passed the first reviewer and approver; caught by a later reconciliation.", "core"),
    "PS05": (SEC, CHG, "Untested database field limit broke government-securities settlement; Fed overdraft of USD 23.6bn.", "core"),
    "PS06": (STR, CAP, "Structured notes issued above the registered shelf amount; no automated check of issuance against the limit.", "core"),
    "EX07": (STR, CAP, "Product parameters of structured certificates keyed in without a check; sold at a fraction of fair value.", "core"),
    "CY01": (PAY, MSG, "Fraudulent SWIFT messages from a compromised terminal; nostro statement printing disabled, so reconciliation was late.", "core"),
    "SM39": (PAY, MSG, "Third-party payment instructions not verified after a cyber fraud.", "core"),
    "MO01": (FX, SETT, "Scheduled FX-swap leg released to a counterparty already in default; no stop linked to credit events.", "core"),
    "MO02": (PAY, CHG, "SWIFT system configuration change made the payment software resend payments in a loop; no duplicate check.", "core"),
    "MO03": (PAY, SETT, "Payment batch released twice by a scheduling error; no duplicate-file control.", "core"),
    "MO04": (PAY, CHG, "After a system update, failed incoming transfers were credited as received; no check that funds had settled.", "core"),
    "MO05": (PAY, NOST, "SWIFT commitments not reconciled to core banking; nostro reconciliation did not flag incoming funds moved out.", "core"),
    "MO06": (IRD, CHG, "Zero-coupon swaps keyed in wrongly during a system migration; no trade-by-trade reconciliation until a swap matured.", "core"),
    "MO07": (OTH, IPV, "Trader marks on ABS not challenged by price verification.", "analog"),
    "MO08": (IRD, CAP, "Repo and interest rate swap booked as separate trades though contractually linked; agreement kept outside the books.", "core"),
    "MO09": (FXO, IPV, "Volatilities of illiquid emerging-market FX options marked by traders and not independently verified.", "core"),
    "MO10": (FX, SETT, "Principal paid away before the counter-currency was received (no payment-versus-payment).", "core"),
    "MO11": (PAY, MSG, "Fraudulent SWIFT transfers with stolen credentials; messages not reconciled to the core system.", "core"),
    "MO12": (PAY, MSG, "Fraudulent SWIFT transfers sent by malware; most recovered.", "core"),
    "MO13": (PAY, NOST, "Control that WORKED: SWIFT confirmations reconciled against payment orders caught USD 110m of fraudulent transfers.", "core"),
    "MO14": (PAY, MSG, "Fraudulent SWIFT transfers sent while a wiper attack distracted the bank.", "core"),
    "RT04": (FXO, CONF, "Fictitious FX option trades never confirmed with counterparties; back office accepted the trader's rate feed for revaluation.", "core"),
    "RT05": (FXO, IPV, "FX option revaluation rates supplied by the desk; limit breaches and confirmation queries not escalated.", "core"),
    "RT06": (OTH, CONF, "Fictitious forwards with 'pending' counterparties; confirmation and nominal alerts not escalated.", "analog"),
    "RT07": (OTH, SETT, "Forward-settling ETF trades booked as hedges were never settled; operations did not chase unsettled trades.", "analog"),
    "RT08": (OTH, CAP, "Manual futures trade entries not reconciled to exchange records intraday.", "analog"),
    "RT17": (OTH, CAP, "Booking system recognised profit on unsettled forward bond reconstitutions; no validation of the economics.", "analog"),
    "RT01": (OTH, NOST, "Margin funding requests not reconciled to positions; one person ran trading and settlement.", "analog"),
    "RT02": (OTH, NOST, "Trader also controlled settlement and custody records; custody holdings not independently confirmed.", "analog"),
    "RT03": (OTH, CONF, "Off-book trades with forged confirmations; counterparty confirmations not obtained independently.", "analog"),
    "RT20": (OTH, CAP, "Buy keyed as a sell; no independent check of trade entry against the order.", "analog"),
    "OD07": (OTH, CAP, "Hundreds of fictitious trades over 18 months not detected by trade validation and price checks.", "analog"),
    "SM09": (OTH, CAP, "Cross trade between funds booked at an off-market price; middle-office price check missing.", "analog"),
    "MV01": (OTH, IPV, "Credit derivatives marked at the edge of bid-offer; spreadsheet VaR model error not validated.", "analog"),
    "MV02": (OTH, IPV, "Option prices verified against quotes from a single colluding broker.", "analog"),
    "MV03": (IRD, IPV, "Interest rate option (swaption) volatilities supplied by the trader and not independently verified.", "core"),
    "MV04": (OTH, IPV, "Credit-index option marks not independently verified.", "analog"),
    "MV05": (OTH, IPV, "Equity derivatives valued by traders; bank lost its licence.", "analog"),
    "CM01": (PAY, SETT, "Client money transferred out of segregated accounts to meet liquidity needs; transfer controls overridden.", "core"),
    "CM04": (OTH, NOST, "Client money held in house accounts after a systems change; daily segregation reconciliation wrong for years.", "analog"),
    "CP01": (SEC, COLL, "Static margin terms and repeated limit breaches on a hedge-fund client; margin calls not enforced.", "core"),
    "SM36": (IRD, CAP, "Controls over benchmark rate input data contributed by the bank were ineffective.", "core"),
    "OD16": (IRD, REP, "Over 20m swaps back-reported; swap data and margin notices inaccurate.", "core"),
    "OD17": (FX, REP, "FX forwards reported as FX spot; collateralised swaps reported as uncollateralised.", "core"),
    "SM28": (FX, REP, "Over 40m swaps under- or misreported (FX classification).", "core"),
    "SM29": (IRD, REP, "Nearly 4m swaps unreported or misreported due to allocation errors.", "core"),
    "SM30": (IRD, REP, "At least 5m swaps misreported, breaching an earlier remediation order.", "core"),
    "SM31": (IRD, REP, "Swap data repeatedly reported late.", "core"),
    "SM32": (IRD, REP, "Millions of swaps reported wrongly or late (duplicate IDs, wrong terms).", "core"),
}

# Scenario prompts per process step (expert synthesis for workshops)
STEPS = {
    CAP: {"validation": "Trade booked matches the deal (economics, counterparty, product parameters); booked within limits; linked trades booked as one.",
          "scenario": "A structured or derivative trade is booked with a wrong parameter (notional, strike, barrier, unit) or as separate legs, and the error runs undetected until a cash flow or maturity."},
    CONF: {"validation": "Every OTC trade is confirmed directly with the counterparty, unmatched or unconfirmed trades are aged and escalated.",
           "scenario": "Fictitious or mis-booked FX option or swap trades remain unconfirmed for months because confirmation exceptions are accepted or routed back to the desk."},
    SETT: {"validation": "Payments are released only after four-eye or six-eye checks, duplicate and amount-limit checks, and a stop on counterparties in default.",
           "scenario": "A large FX or money-market payment is released with the wrong amount, twice, or to a counterparty that has just defaulted, and cannot be recalled."},
    NOST: {"validation": "Nostro statements (MT950/camt.053) and SWIFT traffic are reconciled to the books daily and breaks are aged and escalated.",
           "scenario": "Incoming or outgoing funds on a nostro do not match booked trades, but breaks are left open, so a fraud or error builds up for months."},
    IPV: {"validation": "Every position is revalued with market data independent of the desk (rates, FX vols, swaption vols), with challenge of stale or single-source quotes.",
          "scenario": "Illiquid FX option or swaption volatilities are taken from the desk or one broker; a later independent revaluation forces a large write-down."},
    COLL: {"validation": "Collateral calls and transfers are calculated from validated exposures and checked for amount and counterparty before release.",
           "scenario": "A collateral transfer to a clearing house or counterparty is sent with the wrong amount, or margin calls on a large client are not enforced."},
    CHG: {"validation": "System changes and migrations are tested, and positions and cash flows are reconciled trade by trade before and after go-live.",
          "scenario": "A payment or trading-system change (SWIFT, settlement or rates engine) creates duplicate payments or wrongly migrated swap cash flows."},
    MSG: {"validation": "SWIFT access is secured and outgoing messages are matched to approved payment orders before and after sending.",
          "scenario": "Fraudulent SWIFT payments are sent from the bank's own terminal outside office hours and are noticed only on the next nostro statement."},
    REP: {"validation": "Trade reports (EMIR, CFTC) are reconciled to the books for completeness and accuracy, with classification checks (spot vs forward).",
          "scenario": "Years of FX forward or swap reports are incomplete or misclassified, leading to back-reporting and a regulatory fine."},
}


def main():
    lib = {r["event_id"]: r for r in csv.DictReader(open(HERE / "extreme_events.csv", encoding="utf-8"))}
    missing = [k for k in TAGS if k not in lib]
    if missing:
        raise KeyError(f"not in library: {missing}")
    keep = ["event_id", "announced", "year", "firm", "country", "region", "loss_usd_m", "near_miss", "exposure_usd_m",
            "loss_band", "internal_fraud", "basel_event_type", "what_happened", "loss_components", "years_undetected",
            "official_source", "source_1", "source_2", "confidence"]
    rows = []
    for k, (prod, step, val, rel) in TAGS.items():
        r = {c: lib[k][c] for c in keep}
        r.update(product=prod, process_step=step, validation_failed=val, relevance=rel)
        rows.append(r)
    rows.sort(key=lambda r: (r["process_step"], r["announced"]))
    cols = ["event_id", "announced", "firm", "product", "process_step", "validation_failed", "relevance", "internal_fraud",
            "loss_usd_m", "near_miss", "exposure_usd_m", "loss_band", "region", "country", "year", "basel_event_type",
            "what_happened", "loss_components", "years_undetected", "official_source", "source_1", "source_2", "confidence"]
    with open(HERE / "market_ops_bo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    num = lambda v: float(v) if v not in ("", None) else None
    js = [{**r, "loss_usd_m": num(r["loss_usd_m"]), "exposure_usd_m": num(r["exposure_usd_m"]),
           "years_undetected": num(r["years_undetected"])} for r in rows]
    (HERE / "market_ops_bo.json").write_text(json.dumps({"events": js, "steps": STEPS,
                                                         "products": [FX, FXO, IRD, STR, MM, PAY, SEC, OTH]}, ensure_ascii=False))
    print(f"{len(rows)} market-ops events ({sum(r['relevance'] == 'core' for r in rows)} core)")


if __name__ == "__main__":
    main()
