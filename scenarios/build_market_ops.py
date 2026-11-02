"""Market-operations back-office view of the Extreme Loss Library, for a bank that
serves clients and interbank counterparties, hedges client deals back-to-back and holds
only small own risk-management positions (no trading book).

Each event is tagged with product, process step, the validation that failed, where the
exposure came from (client, interbank counterparty, back-to-back hedge, own positions,
payments and nostro, regulatory) and its fit to that business model:
  High   = same product and process as a client / back-to-back / payments flow
  Medium = same validation, different scale or product; or front-office led
  Low    = needs a large trading book; keep only as a stress anchor
Output: market_ops_bo.csv / .json
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
ONB, CAP, CONF, IPV, COLL, SETT, INSTR, NOST, BILL, REP, CHG = (
    "Client & counterparty onboarding, capacity and limits", "Trade capture & back-to-back matching",
    "Confirmation & matching", "Independent price verification", "Collateral, margin & credit limits",
    "Payment release & settlement", "Payment instruction verification & message security",
    "Nostro & cash reconciliation", "Client rates, charges & interest", "Regulatory trade reporting",
    "System change & static data")
ORDER = [ONB, CAP, CONF, IPV, COLL, SETT, INSTR, NOST, BILL, REP, CHG]
CLI, CPT, B2B, OWN, PAYS, REG = ("Client", "Interbank counterparty", "Back-to-back hedge", "Own positions",
                                  "Payments & nostro", "Regulatory")

# id: (product, step, validation that failed, exposure source, fit, why it fits)
TAGS = {
    # ---- client & counterparty onboarding
    "MO15": (IRD, ONB, "Banks did not verify that local-authority clients had legal capacity to enter swaps; 600+ contracts void.", CLI, "High",
             "Any public-sector, municipal or special-purpose client: capacity and authorised signatories."),
    "MO19": (FXO, ONB, "FX option hedges sold to exporters in excess of their real FX exposure; banks compensated clients.", CLI, "High",
             "Client FX options and forwards: hedge size vs underlying exposure. Front-office led, back office can flag."),
    "MO20": (OTH, ONB, "Credit and trading facilities given to a client trader without checking activity against the client's mandate.", CLI, "Medium",
             "Client trader acting beyond mandate; corporate treasury clients."),
    # ---- trade capture & back-to-back matching
    "MO16": (STR, CAP, "Hedge of a client structured bond re-registered wrongly; unhedged for weeks.", B2B, "High",
             "Exactly the back-to-back risk: client deal and hedge not matched daily."),
    "EX07": (STR, CAP, "Structured certificate parameters keyed without a check; sold to clients at a fraction of value.", CLI, "High",
             "Structured products for clients: term-sheet vs booking check."),
    "PS06": (STR, CAP, "Structured notes issued above the registered amount; no automated limit check.", CLI, "Medium",
             "Applies if the bank issues notes; for a distributor, the issuance check sits with the issuer."),
    "MO08": (IRD, CAP, "Repo and interest rate swap booked as separate trades though contractually linked.", OWN, "Medium",
             "Linked trades in own risk-management positions."),
    "RT20": (OTH, CAP, "Buy keyed as a sell; no check of the booking against the order.", OWN, "Medium",
             "Wrong direction on a hedge leg leaves the bank double exposed instead of flat."),
    "OD07": (OTH, CAP, "Hundreds of fictitious trades not caught by trade validation.", OWN, "Medium", "Same validation on a smaller book."),
    "SM09": (OTH, CAP, "Trade between client funds booked at an off-market price; no price check at entry.", CLI, "Medium",
             "Off-market rates on client deals."),
    "RT08": (OTH, CAP, "Manual trade entries not reconciled to the exchange.", OWN, "Low", "Large trading book."),
    "RT17": (OTH, CAP, "System booked profit on unsettled forward trades.", OWN, "Low", "Large trading book."),
    "SM36": (IRD, CAP, "Benchmark input data contributed by the bank not controlled.", OWN, "Low", "Only for benchmark contributors."),
    # ---- confirmations
    "RT04": (FXO, CONF, "Fictitious FX options never confirmed with counterparties; revaluation rates taken from the trader.", OWN, "High",
             "Small FX desk at a regional bank: the closest match to a bank with small own positions."),
    "RT03": (OTH, CONF, "Client's trader dealt off-book; confirmations went to the trader, not to independent staff.", CLI, "Medium",
             "Send client confirmations to someone independent of the dealer."),
    "RT06": (OTH, CONF, "Fictitious forwards with 'pending' counterparties; alerts not escalated.", OWN, "Low", "Large trading book."),
    # ---- price verification
    "RT05": (FXO, IPV, "FX option revaluation rates supplied by the desk.", OWN, "Medium", "Residual FX option risk after back-to-back hedging."),
    "MO09": (FXO, IPV, "Illiquid EM FX option volatilities marked by traders.", OWN, "Medium", "Residual FX option risk; illiquid currency pairs."),
    "MV03": (IRD, IPV, "Swaption volatilities supplied by the trader.", OWN, "Medium", "Unhedged swaption, cap or floor residuals."),
    "MO07": (OTH, IPV, "Trader marks on ABS not challenged.", OWN, "Low", "Large trading book."),
    "MV01": (OTH, IPV, "Marks at the edge of bid-offer; spreadsheet model error.", OWN, "Low", "Large trading book."),
    "MV02": (OTH, IPV, "Prices verified against one colluding broker.", OWN, "Low", "Large trading book."),
    "MV04": (OTH, IPV, "Option marks not verified.", OWN, "Low", "Large trading book."),
    "MV05": (OTH, IPV, "Derivatives valued by traders.", OWN, "Low", "Large trading book."),
    # ---- collateral, margin & credit limits
    "MO17": (FX, COLL, "Client margin did not cover a currency gap; client losses exceeded collateral.", CLI, "High",
             "Client FX forwards and options on credit lines: gap-risk and margin on a peg or managed currency."),
    "MO18": (FX, COLL, "Client margin set for normal volatility.", CLI, "Medium", "Same as above; retail broker setting."),
    "CP01": (SEC, COLL, "Static margin and repeated limit breaches on a client not enforced.", CLI, "Medium",
             "Client limit breaches tolerated; scale is prime brokerage."),
    "PS03": (SEC, COLL, "Collateral transfer sent with the wrong amount (EUR 28bn); recalled.", CPT, "Medium", "CSA and clearing margin transfers."),
    # ---- payment release & settlement
    "MO01": (FX, SETT, "FX-swap leg released to a counterparty already in default.", CPT, "High",
             "Interbank FX and FX swaps: stop payments on a credit event."),
    "MO10": (FX, SETT, "Principal paid away before the counter-currency arrived (no PvP).", CPT, "High",
             "FX settled outside CLS with counterparties and clients."),
    "PS02": (FX, SETT, "Gross instead of net amount sent; four-eye check missing.", CLI, "High", "FX settlement with clients."),
    "PS01": (MM, SETT, "Principal paid instead of interest via manual override; three approvers passed it.", CLI, "High",
             "Loan and deposit payments to clients."),
    "PS04": (PAY, SETT, "Amount with extra zeros passed two approvers.", CLI, "High", "Any manual payment entry."),
    "MO03": (PAY, SETT, "Payment batch released twice.", CLI, "High", "Bulk client payments."),
    "CM01": (PAY, SETT, "Client money moved out of segregated accounts under liquidity stress.", CLI, "Medium", "Client cash and margin accounts."),
    "RT07": (OTH, SETT, "Forward-settling trades never settled; not chased.", OWN, "Low", "Large trading book."),
    # ---- instruction verification & message security
    "MO21": (PAY, INSTR, "Client instruction executed without call-back to the account holder; signature mismatch ignored.", CLI, "High",
             "Client payment and settlement instructions."),
    "SM39": (PAY, INSTR, "Third-party payment instructions not verified.", CLI, "High", "Client payment instructions."),
    "CY01": (PAY, INSTR, "Fraudulent SWIFT messages from the bank's own terminal; statements not reviewed in time.", PAYS, "High", "SWIFT and nostros."),
    "MO11": (PAY, INSTR, "Fraudulent SWIFT transfers with stolen credentials.", PAYS, "High", "SWIFT and nostros."),
    "MO12": (PAY, INSTR, "Fraudulent SWIFT transfers sent by malware.", PAYS, "High", "SWIFT and nostros."),
    "MO14": (PAY, INSTR, "Fraudulent SWIFT transfers during a wiper attack.", PAYS, "High", "SWIFT and nostros."),
    # ---- nostro & cash reconciliation
    "MO05": (PAY, NOST, "SWIFT commitments not reconciled to core banking; nostro breaks not escalated.", PAYS, "High", "SWIFT vs core banking vs nostro."),
    "MO13": (PAY, NOST, "Control that WORKED: SWIFT confirmations reconciled to payment orders caught USD 110m.", PAYS, "High", "Same-day SWIFT reconciliation."),
    "RT01": (OTH, NOST, "Funding requests not reconciled to positions; one person in front and back office.", OWN, "Medium", "Small overseas office."),
    "RT02": (OTH, NOST, "Trader controlled settlement and custody records.", OWN, "Medium", "Segregation of duties in a small office."),
    "CM04": (OTH, NOST, "Client money in house accounts after a systems change.", CLI, "Medium", "Client cash accounts."),
    # ---- client rates, charges & interest
    "MC06": (FX, BILL, "FX rates applied to custody clients differed from what clients were told.", CLI, "High", "Client FX rates and spreads."),
    "MC07": (FX, BILL, "FX rates applied to custody clients differed from what clients were told.", CLI, "High", "Client FX rates and spreads."),
    "AP01": (STR, BILL, "Spreads on bond and structured-product trades not checked against client agreements.", CLI, "High", "Client spreads on structured products."),
    "SM05": (FX, BILL, "Price improvements kept from clients; asymmetric slippage.", CLI, "Medium", "Client FX execution."),
    # ---- regulatory reporting
    "OD17": (FX, REP, "FX forwards reported as spot; collateral flags wrong.", REG, "High", "EMIR reporting of client FX forwards."),
    "SM28": (FX, REP, "Over 40m swaps misreported (FX classification).", REG, "High", "EMIR reporting of client FX."),
    "OD16": (IRD, REP, "Over 20m swaps back-reported.", REG, "Medium", "Swap reporting."),
    "SM29": (IRD, REP, "Allocation errors in swap reports.", REG, "Medium", "Swap reporting."),
    "SM30": (IRD, REP, "Swaps misreported, breaching an earlier order.", REG, "Medium", "Swap reporting."),
    "SM31": (IRD, REP, "Swap data reported late.", REG, "Medium", "Swap reporting."),
    "SM32": (IRD, REP, "Swaps reported wrongly or late.", REG, "Medium", "Swap reporting."),
    # ---- system change & static data
    "MO06": (IRD, CHG, "Swaps keyed wrongly in a system migration; not reconciled until a swap matured.", B2B, "High",
             "Migration of client and hedge swaps: reconcile cash flows trade by trade."),
    "MO02": (PAY, CHG, "SWIFT configuration change sent payments in a loop.", PAYS, "High", "Payment system changes."),
    "MO04": (PAY, CHG, "After an update, failed incoming transfers were credited as received.", PAYS, "High", "Payment system changes."),
    "PS05": (SEC, CHG, "Untested field limit broke securities settlement.", PAYS, "Medium", "Settlement system changes."),
}

STEPS = {
    ONB: {"validation": "Before the first deal: legal capacity and authorised signatories, ISDA/CSA in place, credit line, and hedge size vs the client's real exposure.",
          "scenario": "A client (municipality, SME or corporate treasury) disputes or cannot honour derivative deals because it lacked capacity or authority, or the hedge was larger than its exposure."},
    CAP: {"validation": "Every client deal has a matching hedge (same notional, dates, strike, direction) and both match the term sheet; mismatches are flagged the same day.",
          "scenario": "A client FX option or structured product is hedged with a wrong leg (direction, notional or barrier), and the bank is unhedged until a fixing or maturity."},
    CONF: {"validation": "Client and counterparty confirmations are sent and matched by staff independent of the dealer; unconfirmed trades are aged and escalated.",
           "scenario": "Unconfirmed client or interbank deals pile up; a fictitious or disputed trade is found months later."},
    IPV: {"validation": "Residual own positions and the client/hedge pairs are revalued with independent rates and volatilities.",
          "scenario": "A small own FX option or swaption position is marked by the desk; independent revaluation forces a write-down."},
    COLL: {"validation": "Client exposures on forwards and options are compared with credit lines and collateral daily, with gap-risk stress for pegged currencies.",
           "scenario": "A sudden currency move (like the 2015 Swiss franc unpeg) leaves client losses above collateral and credit lines, and clients default."},
    SETT: {"validation": "Payments are released after four-eye checks, duplicate and amount-limit checks, and are stopped for counterparties in default.",
           "scenario": "An FX or money-market payment goes out with the wrong amount, twice, or to a counterparty that defaulted that morning."},
    INSTR: {"validation": "Client instructions and changes to settlement instructions are verified by call-back; SWIFT access is secured and messages matched to approved orders.",
            "scenario": "A fraudster changes a client's settlement instructions or sends SWIFT messages from the bank's own terminal."},
    NOST: {"validation": "Nostro statements and SWIFT traffic are reconciled to the books the same day; breaks are aged and escalated.",
           "scenario": "Breaks on a nostro are left open and a fraud or payment error builds up for weeks."},
    BILL: {"validation": "Rates, spreads and interest charged to clients are checked against the agreed terms.",
           "scenario": "Client FX spreads or interest are charged above agreement for years, leading to restitution and fines."},
    REP: {"validation": "EMIR/CFTC reports are reconciled to the books, including product classification (spot vs forward).",
          "scenario": "Years of client FX forwards are misreported, leading to back-reporting and a fine."},
    CHG: {"validation": "Changes and migrations of payment and derivatives systems are tested and reconciled trade by trade and cash flow by cash flow.",
          "scenario": "A payment-system or swaps-system change duplicates payments or migrates client and hedge cash flows wrongly."},
}


def main():
    lib = {r["event_id"]: r for r in csv.DictReader(open(HERE / "extreme_events.csv", encoding="utf-8"))}
    missing = [k for k in TAGS if k not in lib]
    if missing:
        raise KeyError(f"not in library: {missing}")
    keep = ["event_id", "announced", "year", "firm", "country", "region", "loss_usd_m", "near_miss", "exposure_usd_m",
            "loss_band", "internal_fraud", "basel_event_type", "what_happened", "loss_components", "years_undetected",
            "official_source", "source_1", "source_2", "confidence"]
    rank = {"High": 0, "Medium": 1, "Low": 2}
    rows = []
    for k, (prod, step, val, src, fit, why) in TAGS.items():
        r = {c: lib[k][c] for c in keep}
        r.update(product=prod, process_step=step, validation_failed=val, exposure_source=src, fit=fit, fit_reason=why)
        rows.append(r)
    rows.sort(key=lambda r: (ORDER.index(r["process_step"]), rank[r["fit"]], r["announced"]))
    cols = ["event_id", "announced", "firm", "fit", "fit_reason", "exposure_source", "product", "process_step", "validation_failed",
            "internal_fraud", "loss_usd_m", "near_miss", "exposure_usd_m", "loss_band", "region", "country", "year",
            "basel_event_type", "what_happened", "loss_components", "years_undetected", "official_source", "source_1",
            "source_2", "confidence"]
    with open(HERE / "market_ops_bo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    num = lambda v: float(v) if v not in ("", None) else None
    js = [{**r, "loss_usd_m": num(r["loss_usd_m"]), "exposure_usd_m": num(r["exposure_usd_m"])} for r in rows]
    (HERE / "market_ops_bo.json").write_text(json.dumps({
        "events": js, "steps": STEPS, "order": ORDER, "products": [FX, FXO, IRD, STR, MM, PAY, SEC, OTH],
        "sources": [CLI, CPT, B2B, PAYS, OWN, REG]}, ensure_ascii=False))
    from collections import Counter
    print(len(rows), Counter(r["fit"] for r in rows), Counter(r["exposure_source"] for r in rows))


if __name__ == "__main__":
    main()
