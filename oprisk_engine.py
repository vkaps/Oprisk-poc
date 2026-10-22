"""
oprisk_engine.py - Operational risk PoC: market-abuse fines
============================================================

Estimates, for ONE anonymous bank, the annual probability and impact of
regulatory fines linked to financial-markets events, in four separate cells:

    A1  inside information  - fine on the BANK
    A2  inside information  - fine on an EMPLOYEE of the bank
    B1  market manipulation - fine on the BANK
    B2  market manipulation - fine on an EMPLOYEE of the bank

Pipeline
    1. events      -> cluster fines that share a root cause into one event
    2. exposure    -> peer bank-years (size, region) = the denominator
    3. threshold   -> estimate where public reporting becomes complete
    4. frequency   -> negative-binomial GLM per cell, log(size) scaling
    5. Bayes       -> Gamma-Poisson update with the bank's own history
    6. severity    -> size-scaled lognormal (+ GPD tail when data allow)
    7. Monte Carlo -> annual loss distribution per cell and combined

Only numpy / scipy / pandas / matplotlib are required.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.special import gammaln

CELLS = ["A1", "A2", "B1", "B2", "M1", "M2"]
CELL_LABELS = {
    "A1": "Inside information - bank sanctioned",
    "A2": "Inside information - employee sanctioned or convicted",
    "B1": "Market manipulation - bank sanctioned",
    "B2": "Market manipulation - employee sanctioned or convicted",
    "M1": "All market abuse - bank sanctioned (A1+B1+type unknown)",
    "M2": "All market abuse - employee sanctioned or convicted (A2+B2+type unknown)",
}
# Events whose type is unknown (e.g. ESMA register, no text) only enter M1/M2.
CATEGORY_CODE = {"inside_information": "A", "market_manipulation": "B",
                 "market_abuse_unspecified": "U"}
MEMBERS = {"A1": ["A1"], "A2": ["A2"], "B1": ["B1"], "B2": ["B2"],
           "M1": ["A1", "B1", "U1"], "M2": ["A2", "B2", "U2"]}
PARTY_CODE = {"bank": "1", "employee": "2"}

# Regulatory regimes (EU view; applied to all regions as a time effect)
PERIODS = [("pre_MAD", 1900, 2004), ("MAD", 2005, 2015), ("MAR", 2016, 2100)]


def period_of(year: int) -> str:
    for name, lo, hi in PERIODS:
        if lo <= year <= hi:
            return name
    raise ValueError(year)


# ---------------------------------------------------------------------------
# 1. Events
# ---------------------------------------------------------------------------
EVENT_COLUMNS = [
    "notice_id", "cluster_id", "date", "regulator", "country", "peer_id",
    "penalised_party", "category", "amount_eur", "description", "source_url", "source",
]


def add_cell(events: pd.DataFrame) -> pd.DataFrame:
    ev = events.copy()
    ev["cell"] = ev["category"].map(CATEGORY_CODE) + ev["penalised_party"].map(PARTY_CODE)
    bad = ev["cell"].isna()
    if bad.any():
        raise ValueError(f"{bad.sum()} rows have unknown category/penalised_party values")
    return ev


def cluster_events(notices: pd.DataFrame) -> pd.DataFrame:
    """One row per event. Notices sharing cluster_id (same root cause, e.g. one
    scandal fined by several regulators) are merged: first date, summed amount."""
    ev = add_cell(notices)
    ev["date"] = pd.to_datetime(ev["date"])
    ev["cluster_id"] = ev["cluster_id"].fillna(ev["notice_id"]).astype(str)
    g = ev.groupby(["cluster_id", "peer_id", "cell"], as_index=False).agg(
        date=("date", "min"),
        amount_eur=("amount_eur", lambda s: s.sum(min_count=1)),  # stays NaN if unknown
        n_notices=("notice_id", "count"),
        outcome=("outcome", lambda s: "; ".join(sorted(set(map(str, s.dropna())))) or "fine")
        if "outcome" in ev else ("notice_id", lambda s: "fine"),
        regulators=("regulator", lambda s: "; ".join(sorted(set(map(str, s))))),
    )
    g["year"] = g["date"].dt.year
    return g


# ---------------------------------------------------------------------------
# 2. Exposure panel
# ---------------------------------------------------------------------------
def build_counts(panel: pd.DataFrame, events: pd.DataFrame, cell: str,
                 min_amount: float = 0.0) -> pd.DataFrame:
    """Peer bank-year panel with event counts for one cell. Every bank-year of the
    panel is kept, so banks with no event count as zeros (the non-events).
    Events with an unknown amount are always counted: they are real events."""
    p = panel.copy()
    amt = events["amount_eur"]
    e = events[events["cell"].isin(MEMBERS[cell]) & (amt.isna() | (amt >= min_amount))]
    c = e.groupby(["peer_id", "year"]).size().rename("n").reset_index()
    p = p.merge(c, on=["peer_id", "year"], how="left")
    p["n"] = p["n"].fillna(0).astype(int)
    p["log_size"] = np.log(p["total_assets_eur_bn"])
    p["period"] = p["year"].map(period_of)
    return p


def apply_coverage(panel: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    """Keep only bank-years whose region/years were actually searched for fines.
    A year nobody searched is not a 'zero-event' year: counting it would bias
    the rate downwards. coverage columns: region, first_year, last_year."""
    keep = pd.Series(False, index=panel.index)
    for _, c in coverage.iterrows():
        keep |= (panel["region"] == c["region"]) & panel["year"].between(c["first_year"], c["last_year"])
    return panel[keep].copy()


# ---------------------------------------------------------------------------
# 3. Effective reporting threshold
# ---------------------------------------------------------------------------
def reporting_threshold(amounts: np.ndarray) -> float:
    """Below the mode of the (log) amount density, public data is incomplete:
    real losses get more frequent as they get smaller, so a density that falls
    towards small amounts signals under-reporting. The mode is the lowest
    amount from which the sample can be treated as complete."""
    a = np.asarray(amounts, float)
    a = a[a > 0]
    if len(a) < 10:
        return float(np.min(a)) if len(a) else 0.0
    x = np.log(a)
    kde = stats.gaussian_kde(x)
    grid = np.linspace(x.min(), x.max(), 512)
    return float(np.exp(grid[np.argmax(kde(grid))]))


# ---------------------------------------------------------------------------
# 4. Frequency: negative binomial (NB2) GLM, MAP with weak normal prior
# ---------------------------------------------------------------------------
class NBFit:
    def __init__(self, names, beta, alpha, cov, size_center, n_obs, n_events):
        self.names, self.beta, self.alpha, self.cov = names, beta, alpha, cov
        self.size_center, self.n_obs, self.n_events = size_center, n_obs, n_events

    @property
    def r(self) -> float:
        """Gamma shape of between-bank heterogeneity (= 1/alpha)."""
        return 1.0 / max(self.alpha, 1e-8)

    def table(self) -> pd.DataFrame:
        se = np.sqrt(np.clip(np.diag(self.cov)[: len(self.beta)], 0, None))
        return pd.DataFrame({"coef": self.beta, "std_err": se,
                             "rate_multiplier": np.exp(self.beta)}, index=self.names)

    def design(self, log_size, period, region, regions=None) -> np.ndarray:
        """Covariate row. A period or region without its own dummy is the baseline."""
        def val(n):
            if n == "const":
                return 1.0
            if n == "log_size_c":
                return log_size - self.size_center
            if n.startswith("period_"):
                return float(period == n[7:])
            return float(region == n[7:])
        return np.array([val(n) for n in self.names])

    def mu(self, log_size, period, region, regions) -> float:
        return float(np.exp(self.design(log_size, period, region, regions) @ self.beta))


def fit_nb(counts: pd.DataFrame, regions: list[str], prior_sd: float = 2.0,
           use_size: bool = True) -> NBFit:
    """NB2 regression of yearly event counts.
    log mu = b0 + b1*(log size - centre) + period effects + region effects.
    Baselines are the first regime and first region present in the data (so the
    dummies are never collinear with the intercept).
    Priors (MAP = penalised maximum likelihood), needed because events are rare:
      * effects ~ N(0, prior_sd)
      * intercept ~ N(log((n + 0.5) / bank-years), 1.5): with zero events the rate
        is "rare" (about half an event over the whole sample), never exactly 0."""
    d = counts
    center = float(d["log_size"].mean())
    cols = {"const": np.ones(len(d))}
    if use_size:  # otherwise every bank has the same rate, whatever its size
        cols["log_size_c"] = d["log_size"].values - center
    present_p = [p for p, *_ in PERIODS if (d["period"] == p).any()]
    for p in present_p[1:]:
        cols[f"period_{p}"] = (d["period"] == p).astype(float).values
    present_r = [r for r in regions if (d["region"] == r).any()]
    for r in present_r[1:]:
        cols[f"region_{r}"] = (d["region"] == r).astype(float).values
    names = list(cols)
    X = np.column_stack([cols[n] for n in names])
    y = d["n"].values.astype(float)
    k = X.shape[1]
    b0_prior = np.log((y.sum() + 0.5) / len(y))

    def nll(theta):
        b, la = theta[:k], theta[k]
        a = np.exp(la)
        mu = np.exp(np.clip(X @ b, -30, 30))
        inv = 1.0 / a
        ll = (gammaln(y + inv) - gammaln(inv) - gammaln(y + 1)
              + inv * np.log(inv / (inv + mu)) + y * np.log(mu / (inv + mu)))
        pen = (0.5 * np.sum(b[1:] ** 2) / prior_sd ** 2 + 0.5 * ((b[0] - b0_prior) / 1.5) ** 2
               + 0.5 * ((la - 0.0) / 3.0) ** 2)
        return -ll.sum() + pen

    b0 = np.zeros(k + 1)
    b0[0] = b0_prior
    res = optimize.minimize(nll, b0, method="BFGS")
    theta = res.x
    H = _num_hessian(nll, theta)
    try:
        cov = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        cov = np.full((k + 1, k + 1), np.nan)
    return NBFit(names, theta[:k], float(np.exp(theta[k])), cov, center, len(d), int(y.sum()))


def _num_hessian(f, x, h=1e-4):
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            e_i, e_j = np.eye(n)[i] * h, np.eye(n)[j] * h
            H[i, j] = H[j, i] = (f(x + e_i + e_j) - f(x + e_i - e_j)
                                 - f(x - e_i + e_j) + f(x - e_i - e_j)) / (4 * h * h)
    return H


def p_at_least_one_nb(mu: float, r: float) -> float:
    """P(N>=1) for NB with mean mu and shape r (Gamma-Poisson)."""
    return 1.0 - (r / (r + mu)) ** r


# ---------------------------------------------------------------------------
# 5. Bayesian update (Gamma-Poisson with size-varying exposure)
# ---------------------------------------------------------------------------
def bayes_update(mu_hist: np.ndarray, n_hist: int, mu_next: float, r: float) -> dict:
    """Bank rate in year t: lambda_t = theta * mu_t, with mu_t from the external
    model (bank size and regime of year t) and theta ~ Gamma(r, rate=r), mean 1.
    theta captures how this bank differs from a typical peer of its size.

    After n events over years with expected counts mu_t:
        theta | data ~ Gamma(r + n, r + sum(mu_t))
    Credibility of internal data Z = sum(mu_t) / (r + sum(mu_t))."""
    E = float(np.sum(mu_hist))
    a_post, b_post = r + n_hist, r + E
    theta_mean = a_post / b_post
    return {
        "prior_lambda": mu_next,
        "prior_P1": p_at_least_one_nb(mu_next, r),
        "expected_internal_events": E,
        "observed_internal_events": n_hist,
        "theta_posterior_mean": theta_mean,
        "posterior_lambda": theta_mean * mu_next,
        # predictive: N | theta ~ Poisson(theta*mu), theta ~ Gamma(a,b)
        "posterior_P1": 1.0 - (b_post / (b_post + mu_next)) ** a_post,
        "credibility_internal": E / (r + E),
        "a_post": a_post, "b_post": b_post, "r_prior": r,
    }


# ---------------------------------------------------------------------------
# 6. Severity
# ---------------------------------------------------------------------------
ELASTICITY_PRIOR = 0.25   # literature range for op-loss severity vs size (Shih et al.; Dahen & Dionne)


def size_elasticity_used(est: float, se: float, n: int, min_n: int = 20) -> tuple[float, str]:
    """Use the estimate only with enough amounts and a plausible value (0-1)."""
    if n >= min_n and np.isfinite(est) and 0 <= est <= 1:
        return est, "estimated"
    return ELASTICITY_PRIOR, f"literature value (estimate {est:.2f} from {n} amounts not reliable)"


def size_elasticity(events: pd.DataFrame, panel: pd.DataFrame) -> tuple[float, float]:
    """OLS slope of log(amount) on log(size of fined/employer bank), with cell
    fixed effects (pooled slope: few events per cell). Returns (slope, std err)."""
    e = events.merge(panel[["peer_id", "year", "total_assets_eur_bn"]],
                     on=["peer_id", "year"], how="inner")
    e = e[e["amount_eur"] > 0]
    if len(e) < 8:
        return 0.0, np.nan
    y = np.log(e["amount_eur"].values)
    X = [np.log(e["total_assets_eur_bn"].values)]
    for c in sorted(e["cell"].unique())[1:]:
        X.append((e["cell"] == c).astype(float).values)
    X = np.column_stack([np.ones(len(e))] + X)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / max(len(y) - X.shape[1], 1)
    cov = s2 * np.linalg.pinv(X.T @ X)
    return float(beta[1]), float(np.sqrt(cov[1, 1]))


def severity_sample(scaled: pd.DataFrame, cell: str, min_n: int = 8) -> tuple[np.ndarray, str]:
    """Known scaled amounts for a cell; pooled with the other cells of the same
    party (bank / employee) when the cell has fewer than min_n amounts."""
    pos = scaled["amount_scaled_eur"] > 0      # outcomes without a fine (0) are not amounts
    x = scaled.loc[scaled["cell"].isin(MEMBERS[cell]) & pos, "amount_scaled_eur"].values
    if len(x) >= min_n:
        return x, "own"
    # pool only with the same party: a fine on a person is not comparable to one on a bank
    party = cell[-1]
    x = scaled.loc[scaled["cell"].str.endswith(party) & pos, "amount_scaled_eur"].values
    return x, f"pooled ({'bank' if party == '1' else 'employee'} cells, {len(x)} amounts)"


def share_without_fine(events: pd.DataFrame, cell: str) -> tuple[float, int, int]:
    """Share of events (with known outcome) that carried no fine, e.g. a criminal
    conviction or a ban. Uses the cell's own events, else the same party."""
    known = events["amount_eur"].notna()
    for sel in (events["cell"].isin(MEMBERS[cell]), events["cell"].str.endswith(cell[-1])):
        k = events[sel & known]
        if len(k) >= 3:
            z = int((k["amount_eur"] == 0).sum())
            return z / len(k), z, len(k)
    return 0.0, 0, 0


def scale_amounts(events: pd.DataFrame, panel: pd.DataFrame, bank_size: float,
                  elasticity: float) -> pd.DataFrame:
    """Express each external fine as the equivalent amount for our bank."""
    e = events.merge(panel[["peer_id", "year", "total_assets_eur_bn"]],
                     on=["peer_id", "year"], how="left")
    ratio = bank_size / e["total_assets_eur_bn"]
    e["amount_scaled_eur"] = e["amount_eur"] * ratio.fillna(1.0) ** elasticity
    return e


class Severity:
    """Lognormal truncated below u (the reporting threshold); optional GPD tail
    spliced above the 90th percentile when at least min_tail exceedances exist."""

    def __init__(self, amounts, u, min_tail=15):
        x = np.asarray(amounts, float)
        x = x[x >= u]
        self.u, self.n = u, len(x)
        lx, lu = np.log(x), np.log(u)

        def nll(t):
            m, s = t[0], np.exp(t[1])
            return -(stats.norm.logpdf(lx, m, s) - stats.norm.logsf(lu, m, s)).sum()

        t0 = [np.mean(lx), np.log(max(np.std(lx), 0.3))]
        res = optimize.minimize(nll, t0, method="Nelder-Mead")
        self.mu_log, self.sigma_log = res.x[0], float(np.exp(res.x[1]))
        self.tail_u = np.quantile(x, 0.9) if len(x) else u
        exc = x[x > self.tail_u] - self.tail_u
        self.gpd = None
        if len(exc) >= min_tail:
            xi, _, beta = stats.genpareto.fit(exc, floc=0)
            # fines are capped by law and by the firm's revenue: keep the mean finite
            if xi > 0.9:
                xi = 0.9
                beta = float(np.mean(exc) * (1 - xi))   # refit scale so the mean excess is kept
            self.gpd = (float(xi), float(beta))
        self.p_tail = float(np.mean(x > self.tail_u)) if len(x) else 0.0

    def describe(self) -> dict:
        d = {"n_used": self.n, "share_no_fine": self.p_zero, "threshold_eur": self.u,
             "lognormal_median_eur": float(np.exp(self.mu_log)),
             "lognormal_sigma": self.sigma_log}
        if self.gpd:
            d.update({"gpd_from_eur": float(self.tail_u), "gpd_shape_xi": self.gpd[0]})
        return d

    p_zero = 0.0   # share of events that end without any fine (set by the caller)

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        out = self._sample(n, rng)
        if self.p_zero > 0 and n:
            out[rng.random(n) < self.p_zero] = 0.0
        return out

    def _sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        lu = np.log(self.u)
        a = (lu - self.mu_log) / self.sigma_log
        z = stats.truncnorm.rvs(a, np.inf, size=n, random_state=rng)
        out = np.exp(self.mu_log + self.sigma_log * z)
        if self.gpd and n:
            tail = rng.random(n) < self.p_tail
            xi, beta = self.gpd
            out[tail] = self.tail_u + stats.genpareto.rvs(xi, scale=beta, size=tail.sum(),
                                                          random_state=rng)
            body = ~tail
            # body: lognormal restricted to [u, tail_u]
            b = (np.log(self.tail_u) - self.mu_log) / self.sigma_log
            if b > a:
                zb = stats.truncnorm.rvs(a, b, size=body.sum(), random_state=rng)
                out[body] = np.exp(self.mu_log + self.sigma_log * zb)
        return out


# ---------------------------------------------------------------------------
# 7. Monte Carlo
# ---------------------------------------------------------------------------
def simulate_annual_loss(a_post: float, b_post: float, mu_next: float, sev: Severity,
                         n_years: int = 200_000, seed: int = 1) -> np.ndarray:
    """Predictive annual loss: theta ~ Gamma(a,b) (parameter uncertainty and
    bank heterogeneity), N ~ Poisson(theta*mu_next), severities from sev."""
    rng = np.random.default_rng(seed)
    theta = rng.gamma(a_post, 1.0 / b_post, n_years)
    N = rng.poisson(theta * mu_next)
    total = np.zeros(n_years)
    k = int(N.sum())
    if k:
        draws = sev.sample(k, rng)
        idx = np.repeat(np.arange(n_years), N)
        np.add.at(total, idx, draws)
    return total


def loss_summary(losses: np.ndarray, levels=(0.95, 0.99, 0.999)) -> dict:
    d = {"P(any fine)": float(np.mean(losses > 0)), "expected_loss_eur": float(losses.mean())}
    for q in levels:
        d[f"VaR_{q:.1%}_eur"] = float(np.quantile(losses, q))
    return d


# ---------------------------------------------------------------------------
# Why negative binomial: Poisson vs NB on the same covariates (no priors)
# ---------------------------------------------------------------------------
def nb_vs_poisson(counts: pd.DataFrame, regions: list[str], kmax: int = 4) -> dict:
    """Fits Poisson and NB2 by plain maximum likelihood with the same regime and
    region terms, then compares
      * the likelihood ratio test for extra spread (alpha = 0 is on the boundary,
        so the p-value is half the chi-square(1) tail);
      * how many banks had 0, 1, 2, ... events in the sample against what each
        model expects (bank totals: Poisson, or Gamma-mixed Poisson = NB)."""
    d = counts
    present_p = [p for p, *_ in PERIODS if (d["period"] == p).any()]
    present_r = [r for r in regions if (d["region"] == r).any()]
    X = np.column_stack([np.ones(len(d))] + [(d["period"] == p).astype(float).values for p in present_p[1:]]
                        + [(d["region"] == r).astype(float).values for r in present_r[1:]])
    y = d["n"].values.astype(float)
    k = X.shape[1]

    def nll_p(b):
        mu = np.exp(np.clip(X @ b, -30, 30))
        return -(y * np.log(mu) - mu - gammaln(y + 1)).sum()

    def nll_nb(t):
        b, a = t[:k], np.exp(t[k])
        mu = np.exp(np.clip(X @ b, -30, 30))
        inv = 1.0 / a
        return -(gammaln(y + inv) - gammaln(inv) - gammaln(y + 1)
                 + inv * np.log(inv / (inv + mu)) + y * np.log(mu / (inv + mu))).sum()

    b0 = np.zeros(k)
    b0[0] = np.log(max(y.mean(), 1e-4))
    rp = optimize.minimize(nll_p, b0, method="BFGS")
    best = None
    for la in (-4.0, -1.0, 0.5, 2.0):   # several starts: the NB likelihood is flat in alpha
        r_ = optimize.minimize(nll_nb, np.r_[rp.x, la], method="Nelder-Mead",
                               options={"maxiter": 40000, "xatol": 1e-8, "fatol": 1e-10})
        if best is None or r_.fun < best.fun:
            best = r_
    alpha = float(np.exp(best.x[k]))
    lr = max(0.0, 2 * (rp.fun - best.fun))
    p = 0.5 * stats.chi2.sf(lr, 1) if lr > 0 else 0.5

    mu_p = np.exp(X @ rp.x)
    mu_nb = np.exp(X @ best.x[:k])
    exp_p = pd.Series(mu_p, index=d.index).groupby(d["peer_id"]).sum()
    exp_nb = pd.Series(mu_nb, index=d.index).groupby(d["peer_id"]).sum()
    tot = d.groupby("peer_id")["n"].sum().reindex(exp_p.index)
    ks = np.arange(kmax + 1)
    obs = [int((tot == j).sum()) if j < kmax else int((tot >= j).sum()) for j in ks]
    pois = [float(stats.poisson.pmf(j, exp_p).sum()) if j < kmax else float(stats.poisson.sf(j - 1, exp_p).sum()) for j in ks]
    r = 1.0 / max(alpha, 1e-6)
    pr = r / (r + exp_nb)
    nbe = [float(stats.nbinom.pmf(j, r, pr).sum()) if j < kmax else float(stats.nbinom.sf(j - 1, r, pr).sum()) for j in ks]
    return {"loglik_poisson": float(-rp.fun), "loglik_nb": float(-best.fun), "alpha_mle": alpha,
            "lr_stat": float(lr), "p_value": float(p), "k": [int(j) for j in ks], "banks_observed": obs,
            "banks_poisson": pois, "banks_nb": nbe, "n_banks": int(len(tot)), "n_events": int(y.sum()),
            "top_banks": tot.sort_values(ascending=False).head(5).astype(int).to_dict()}
