"""Events added for the market-operations back-office focus (IDs MO..).

Same row layout as ROWS in build_extreme_events.py. These also feed the main library.
"""

MARKET_OPS = [
("MO01", "2008-09", "KfW (payment to Lehman Brothers)", "bank", "Germany", "Payment error", "Execution, delivery & process management", "Payment & Settlement",
 "On the day Lehman filed for bankruptcy, KfW's systems still released its leg of a currency swap to Lehman (reported EUR 300-350m); "
 "the counter-payment never came. The finance minister called it a failure of risk management.", 350, "EUR",
 "payment to a defaulted counterparty (reports range EUR 300-350m; total damage estimated up to EUR 536m)", "N", None, 0,
 "No stop on scheduled payments to a counterparty in default; release not linked to credit events",
 "https://www.thelocal.de/20080919/14391", "", "Medium"),
("MO02", "2017-02", "KfW (looping SWIFT payments)", "bank", "Germany", "Back-office input error", "Business disruption & system failures", "Payment & Settlement",
 "A configuration error made during maintenance of the SWIFT payment system caused payments to four banks to be sent repeatedly "
 "(press: about EUR 5bn); the duplicates were returned.", None, "EUR",
 "none after recovery", "Y", 5400, 0, "Change to payment system configuration not tested; no duplicate-payment check",
 "https://www.kfw.de/About-KfW/Newsroom/Latest-News/Zahlungsverkehr-der-KfW.html",
 "https://www.fintechfutures.com/remittances/germany-s-kfw-bank-in-5bn-money-transfer-error", "High"),
("MO03", "2021-12", "Santander UK (duplicate payment run)", "bank", "UK", "Payment error", "Business disruption & system failures", "Payment & Settlement",
 "A scheduling error re-ran a payment file on Christmas Day: about 75,000 payments for 2,000 corporate clients sent twice, "
 "GBP 130m from Santander's own funds; recovery from other banks took weeks.", None, "GBP",
 "recovery effort; final loss not disclosed", "Y", 175, 0, "No control against a payment batch being released twice",
 "https://www.finextra.com/newsarticle/39451/santander-accidentally-sends-customers-130m",
 "https://fortune.com/2021/12/31/santander-bank-accidentally-sent-175-million-payments-christmas-day-wants-money-back", "High"),
("MO04", "2026-10", "Toss Bank (failed transfers credited)", "bank", "South Korea", "Back-office input error", "Business disruption & system failures", "Payment & Settlement",
 "During a remittance-system update, incoming interbank transfers that had failed were credited to customers as normal deposits for 30 minutes; "
 "KRW 32.5bn credited, KRW 7.3bn still being recovered.", None, "KRW",
 "loss not yet final", "Y", 23.4, 0, "Release testing; no check that an incoming transfer had settled before crediting",
 "https://news.jkn.co.kr/editions/english/post/1044464", "", "Medium"),
("MO05", "2018-02", "Punjab National Bank (Nirav Modi LoUs)", "bank", "India", "Client money fraud", "Internal fraud", "Commercial Banking",
 "Staff issued fraudulent letters of undertaking over SWIFT for years; the SWIFT system was not linked to core banking, "
 "so the commitments never appeared in the books and nostro reconciliation did not flag them. About USD 1.77bn.", 1770, "USD",
 "PNB honoured the letters of undertaking to other banks", "N", None, 7,
 "SWIFT messages not reconciled to core banking; nostro reconciliation did not catch incoming funds being moved out",
 "https://www.businesstoday.in/amp/industry/banks/story/pnb-fraud-risk-management-system-to-come-under-rbi-scanner-for-laxity-in-swift-messaging-nostro-reconciliation-101151-2018-02-15",
 "https://www.business-standard.com/amp/article/finance/pnb-misled-rbi-on-swift-integration-central-bank-to-finance-ministry-118040401340_1.html", "Medium"),
("MO06", "2003-02", "DZ Bank (swaps keyed wrongly in system migration)", "bank", "Germany", "Back-office input error", "Execution, delivery & process management", "Trading & Sales",
 "When DG Bank moved to a new trading and risk system in 1999, zero-coupon interest rate swaps were keyed in wrongly; "
 "the mismatch inflated profits for about four years until a swap matured. Loss EUR 40m plus a write-down of over EUR 100m.", 140, "EUR",
 "trading loss 40 + prior-year write-down >100", "N", None, 4,
 "Data migration not reconciled trade by trade; no independent check of swap cash flows until maturity",
 "https://www.risk.net/regulation/1503078/germanys-dz-bank-takes-eu100-million-plus-swaps-hit", "", "High"),
("MO07", "2008-02", "Credit Suisse (ABS mispricing)", "bank", "UK", "Mismarking", "Internal fraud", "Trading & Sales",
 "A handful of traders deliberately mispriced asset-backed securities; the bank wrote down USD 2.85bn days after announcing results. "
 "FSA fine GBP 5.6m for systems and controls failures.", 2850, "USD",
 "write-down 2,850 (not all an operational loss) + FSA fine GBP 5.6m", "N", None, 0,
 "Independent price verification did not challenge trader marks; escalation to regulators slow",
 "https://www.fca.org.uk/publication/final-notices/credit_suisse.pdf",
 "https://www.swissinfo.ch/eng/business/credit-suisse-fined-for-mispricing-scam/6855576", "High"),
("MO08", "2013-02", "Monte dei Paschi (Santorini and Alexandria)", "bank", "Italy", "Concealment by management", "Internal fraud", "Trading & Sales",
 "Structured trades (long-term repos on government bonds with interest rate swaps) were used to hide earlier losses and booked as separate trades; "
 "restatement of about EUR 730m.", 730, "EUR",
 "restatement of derivatives losses", "N", None, 4,
 "Linked trades not identified as one structured transaction; key agreement kept outside the books",
 "https://www.bloomberg.com/news/2013-02-07/paschi-hidden-deals-bring-730-million-euros-of-losses.html", "", "Medium"),
("MO09", "2019-11", "Morgan Stanley (EM FX options mismarking)", "bank", "US/UK", "Mismarking", "Internal fraud", "Trading & Sales",
 "FX traders allegedly mismarked emerging-market currency options to hide losses of USD 100-140m; traders dismissed.", 140, "USD",
 "concealed trading loss (reported range 100-140)", "N", None, None, "Independent price verification of illiquid FX option volatilities",
 "https://www.bloomberg.com/news/articles/2019-11-28/morgan-stanley-ousts-fx-traders-amid-multi-million-dollar-loss", "", "Medium"),
("MO10", "1974-06", "Bankhaus Herstatt (FX settlement)", "bank", "Germany", "Settlement system failure", "Execution, delivery & process management", "Payment & Settlement",
 "Regulators closed Herstatt after the German business day; counterparties that had paid Deutsche marks never received the US dollars. "
 "The origin of the term 'Herstatt risk' and of CLS settlement.", None, "USD",
 "counterparty losses not published as one figure", "N", None, 0, "Principal paid before the counter-currency was received (no payment-versus-payment)",
 "https://www.chicagofed.org/-/media/publications/chicago-fed-letter/2006/cflfebruary2006-223-pdf.pdf",
 "https://bankunderground.co.uk/2015/06/24/boe-archives-reveal-little-known-lesson-from-the-1974-failure-of-herstatt-bank/", "High"),
("MO11", "2016-05", "Banco del Austro (SWIFT fraud)", "bank", "Ecuador", "Cyber theft via payment messages", "External fraud", "Payment & Settlement",
 "Attackers used stolen SWIFT credentials to send fraudulent transfers via Wells Fargo; about USD 12m lost.", 12, "USD",
 "stolen funds", "N", None, None, "Payment messages not reconciled with the core system; credentials not protected",
 "https://thehackernews.com/2017/10/swift-bank-hacking.html", "", "Medium"),
("MO12", "2017-10", "Far Eastern International Bank (SWIFT fraud)", "bank", "Taiwan", "Cyber theft via payment messages", "External fraud", "Payment & Settlement",
 "Malware sent fraudulent SWIFT transfers of nearly USD 60m; most was recovered (about USD 0.5m lost).", None, "USD",
 "about 0.5 unrecovered", "Y", 60, 0, "Payment message monitoring",
 "https://thehackernews.com/2017/10/swift-bank-hacking.html", "", "Medium"),
("MO13", "2018-01", "Bancomext (SWIFT fraud foiled)", "bank", "Mexico", "Cyber theft via payment messages", "External fraud", "Payment & Settlement",
 "Attackers tried to send about USD 110m; a technician reconciling SWIFT confirmations against payment orders spotted the mismatch and the transfers were stopped.", None, "USD",
 "foiled", "Y", 110, 0, "Example of a reconciliation control that worked",
 "https://www.bloomberg.com/news/articles/2018-05-29/mexico-foiled-a-110-million-bank-heist-then-kept-it-a-secret", "", "Medium"),
("MO14", "2018-05", "Banco de Chile (SWIFT fraud)", "bank", "Chile", "Cyber theft via payment messages", "External fraud", "Payment & Settlement",
 "A wiper attack disabled 9,000 computers as cover while fraudulent SWIFT transfers of about USD 10m went to Hong Kong.", 10, "USD",
 "stolen funds", "N", None, 0, "Payment monitoring under incident conditions",
 "https://www.fintechfutures.com/cybersecurity/banco-de-chile-loses-10m-and-9-000-hard-drives-in-hack", "", "Medium"),
]
