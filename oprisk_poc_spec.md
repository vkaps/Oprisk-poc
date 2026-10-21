# Op Risk PoC – Agreed Specification (20 Oct 2026)

## Goal
Estimate, for one undisclosed bank, the annual probability and impact of rare op risk events,
using free external data, scaled to the bank's size, then updated with internal experience (Bayesian).

## Scope (agreed)
- NARROWED (20 Oct, 22:09): only fines/penalties on banks for financial-markets events
  related to inside information (insider dealing, unlawful disclosure of inside information,
  failures in insider lists / suspicious transaction reporting / information barriers).
  Fraud dropped as a separate category.
- Period: 2000 onwards. Regime changes to model as period effects:
  pre-2005 (national rules), 2005-2016 (Market Abuse Directive 2003/6/EC), 2016+ (MAR 596/2014).
  Pre-2016 EU data comes from national regulators (FSA/FCA, CMVM, AMF, BaFin, CONSOB, etc.),
  not ESMA's MAR register.
- No loss threshold in collection (all amounts kept). Modelling will estimate the
  effective reporting threshold of public data and state it explicitly.
- No paid data. Free sources only. P-COLD excluded.
- Bank identity never stored: user inputs only a size table.

## Bank input table (user-filled, anonymous)
| year | size_metric (e.g. total assets, EUR bn) | optional: n_internal_events | optional: internal_loss_EUR |

## Free data sources
- Violation Tracker (US / UK / Global) – free search, parent-linked penalties (no paid export)
- Regulator enforcement pages: ESMA MAR sanctions register, FCA final notices, SEC, CFTC,
  OCC/Fed/CFPB, ECB/SSM sanctions, Banco de Portugal, CMVM, other EU NCAs
- EU Pillar 3 template OR1 (CRR3, from ref. date 31.12.2025) – peer bank-level losses, validation
- BIS Loss Data Collection Exercise results – benchmark/prior
- Peer bank sizes for denominator: ECB list of supervised entities, EBA transparency exercise, bank annual reports

## Method
1. Event table: one row per event; cluster multiple fines from same root cause into one event.
   Map to Basel event types (CPBP improper market practices, internal fraud, external fraud).
2. Exposure panel: peer bank-years with size.
3. Frequency: negative binomial GLM, log(lambda) = b0 + b1*log(size) + event_type + region + period.
4. P(>=1 event/yr) = 1 - (1 + lambda/r)^(-r).
5. Severity: lognormal body + GPD tail, scaled by size; Monte Carlo compound -> annual loss quantiles.
6. Bayesian: Gamma-Poisson per event type. Prior from scaled external lambda with chosen
   "years of evidence" weight; posterior Gamma(a+n, b+T) with internal data; credibility weight T/(b+T).
   Severity prior on GPD shape optional.

## Deliverable
Python notebook (Jupyter) + small input sheet for the bank size table. Build on laptop.

## Open points to confirm on laptop
- Size metric and currency (default: total assets, EUR bn)
- Region focus of peers (default: EU + UK)
- Years covered: 2000 onwards (agreed)
- AGREED: two event categories modelled separately:
  (A) inside information (insider dealing, unlawful disclosure, insider-list/STOR/info-barrier failures)
  (B) market manipulation (spoofing, benchmark rigging, other manipulation)
- AGREED: two penalised-party types kept separate: (1) fines on the bank, (2) fines on its employees
  -> 4 cells (A1, A2, B1, B2), each with its own frequency, probability, severity and Bayesian update.
