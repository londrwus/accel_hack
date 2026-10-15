"""Fund-fit scoring and the time-ordered backtest. Pure numpy + scikit-learn, no Modal and no torch.

modal_app.py imports this inside Modal containers (it is shipped with `add_local_python_source("fitcore")`).
Embeddings come from the caller; this file never loads a text model.

Features per candidate company (all scaled to roughly 0..1):
    sim_max   highest cosine similarity to any portfolio company        ("Very like Cleo")
    sim_mean  average cosine similarity to the portfolio                ("Close to the portfolio as a whole")
    thesis    cosine similarity to the written thesis (Fund DNA)        ("Matches the thesis")
    sector    how much of the fund is in this company's sector          ("Right sector (Fintech)")
    stage     the company's own reported stage vs the fund's stages     ("Right stage (Seed)")
    geo       how much of the fund is in this company's country/region  ("Right location (UK)")
    recency   how recently the company was founded                      ("Founded recently (2024)")

Portfolio companies get leave-one-out features (their own row is never counted), so the model cannot
learn "is in the portfolio" from a similarity of 1.0 to itself.

Never used as features: discovery_source, investors, investor_ids, funding rounds / amounts / dates, and the
`stage` column (it is partly derived from round names, e.g. every Y Combinator round is "pre-seed").
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from datetime import datetime, timezone

import numpy as np

FEATURES = ["sim_max", "sim_mean", "thesis", "sector", "stage", "geo", "recency"]
PART_OF = {
    "sim_max": "Like the portfolio",
    "sim_mean": "Like the portfolio",
    "thesis": "Fits the thesis",
    "sector": "Right sector",
    "stage": "Right stage",
    "geo": "Right location",
    "recency": "Founded recently",
}
PARTS = ["Like the portfolio", "Fits the thesis", "Right sector", "Right stage", "Right location", "Founded recently"]
# Order of the per-result `parts` / `fit_parts` (the design's three bars first; backend/app/agents/ml.py reads `parts`).
FIT_PART_ORDER = ["Like the portfolio", "Right stage", "Right location", "Right sector", "Fits the thesis",
                  "Founded recently"]
MODEL_NAME = "BAAI/bge-base-en-v1.5 embeddings + per-fund logistic regression"
# "What the score depends on" bar labels (Backtest.feature_weights)
WEIGHT_LABEL = {
    "Like the portfolio": "Similar to companies they own",
    "Fits the thesis": "Matches the written thesis",
    "Right sector": "Right sector",
    "Right stage": "Right stage",
    "Right location": "Right location",
    "Founded recently": "Founded recently",
}
WEIGHT_LABEL_NEG = {"Founded recently": "Founded earlier"}
COLORS = ["#5C7A63", "#8FAE96", "#B9CDBC", "#D3AD5E", "#E6D3A8", "#7FA3C0"]

# Used instead of a fitted model when the fund has fewer than MIN_POSITIVES companies we can learn from.
PRIOR_WEIGHTS = {"sim_max": 1.0, "sim_mean": 0.5, "thesis": 1.0, "sector": 0.6, "stage": 0.3, "geo": 0.6, "recency": 0.3}
MIN_POSITIVES = 3
PRIOR_STRENGTH = 10.0  # the default weights count like 10 portfolio companies
RECENCY_PRIOR = 0.3  # fixed weight (per standard deviation) for "founded recently" when the fund backs pre-seed/seed
EARLY_STAGES = {"pre-seed", "seed"}
N_NEGATIVES = 3000
NEVER_USED = ["Gender", "Age", "Ethnicity", "Investor lists", "How we found the company"]

STAGE_KEYS = ["pre-seed", "seed", "series-a", "series-b", "series-c", "growth"]
STAGE_LABEL = {"pre-seed": "Pre-seed", "seed": "Seed", "series-a": "Series A", "series-b": "Series B",
               "series-c": "Series C", "growth": "Growth"}

# Fund DNA sector names (free text) -> dataset sector keys
SECTOR_SYNONYMS = [
    (r"health|medic|care\b|nhs|clinic|pharma", ["healthcare", "biotech"]),
    (r"bio|life science", ["biotech", "healthcare"]),
    (r"fin|payment|bank|money|lending|wealth", ["fintech", "insurtech"]),
    (r"insur", ["insurtech"]),
    (r"deep ?tech|frontier|science|universit", ["deep tech", "frontier tech", "robotics", "semiconductors", "space", "hardware"]),
    (r"climate|sustainab|carbon|green|clean", ["climate", "energy", "agritech"]),
    (r"energy|power|battery", ["energy", "climate"]),
    (r"\bai\b|artificial|machine learning|\bml\b|llm", ["ai"]),
    (r"saas|b2b|software|enterprise|future of work|productivity", ["b2b saas", "dev tools"]),
    (r"developer|dev ?tools|infrastructure|devops", ["dev tools", "b2b saas"]),
    (r"cyber|security", ["cybersecurity"]),
    (r"consumer|d2c|retail|ecommerce|e-commerce|social|media", ["consumer", "marketplace"]),
    (r"marketplace", ["marketplace"]),
    (r"gaming|games", ["gaming"]),
    (r"educat|edtech|learning", ["edtech"]),
    (r"prop|real estate|housing|construction", ["proptech"]),
    (r"mobility|transport|automotive", ["mobility", "logistics"]),
    (r"logistic|supply chain", ["logistics"]),
    (r"crypto|web3|blockchain", ["web3"]),
    (r"defen[cs]e", ["defense"]),
    (r"robot", ["robotics"]),
    (r"space", ["space"]),
    (r"semiconductor|chip", ["semiconductors"]),
    (r"hardware|device", ["hardware"]),
    (r"agri|food", ["agritech"]),
]

EUROPE = ["uk", "ireland", "france", "germany", "spain", "portugal", "italy", "netherlands", "belgium", "luxembourg",
          "switzerland", "austria", "denmark", "sweden", "norway", "finland", "iceland", "estonia", "latvia",
          "lithuania", "poland", "czechia", "hungary", "romania", "greece", "europe", "nordics", "benelux", "cee", "dach"]
GEO_SYNONYMS = [
    (r"\buk\b|united kingdom|britain|british|england|london|scotland", ["uk"]),
    (r"europe|\beu\b|european", EUROPE),
    (r"nordic|scandinavia", ["sweden", "norway", "denmark", "finland", "iceland", "nordics"]),
    (r"dach", ["germany", "austria", "switzerland", "dach"]),
    (r"benelux", ["netherlands", "belgium", "luxembourg", "benelux"]),
    (r"\bcee\b|central and eastern|eastern europe", ["poland", "czechia", "hungary", "romania", "estonia", "latvia",
                                                     "lithuania", "cee"]),
    (r"\bus\b|\busa\b|united states|america\b|silicon valley|new york", ["us", "north america"]),
    (r"north america", ["us", "canada", "north america"]),
    (r"canada", ["canada"]),
    (r"latam|latin america|south america", ["latam", "brazil", "argentina", "mexico", "chile", "colombia"]),
    (r"africa", ["africa", "nigeria", "kenya", "egypt", "south africa"]),
    (r"middle east|mena|gulf", ["middle east", "uae", "saudi arabia", "israel", "egypt", "turkey"]),
    (r"south ?east asia|\bsea\b", ["sea", "singapore", "indonesia", "malaysia", "philippines", "thailand", "vietnam"]),
    (r"\basia\b|apac", ["asia", "sea", "singapore", "indonesia", "malaysia", "philippines", "thailand", "vietnam",
                        "india", "china", "japan", "south korea", "hong kong", "taiwan", "pakistan", "bangladesh",
                        "sri lanka"]),
    (r"australia|anz", ["australia", "new zealand"]),
]
GLOBAL_GEO = re.compile(r"global|anywhere|worldwide", re.I)
LEGAL_SUFFIX = re.compile(
    r"\b(ltd|limited|llc|llp|inc|incorporated|plc|gmbh|sas|sa|sl|srl|bv|ab|as|oy|pty|pte|corp|corporation|co)\b\.?", re.I)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def norm_name(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = LEGAL_SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def domain_of(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)
    s = s.split("/")[0].split("?")[0]
    return s[4:] if s.startswith("www.") else s


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def sector_keys(name: str) -> list[str]:
    low = (name or "").strip().lower()
    if low in {k for _, ks in SECTOR_SYNONYMS for k in ks}:
        return [low]
    out: list[str] = []
    for pat, keys in SECTOR_SYNONYMS:
        if re.search(pat, low):
            out += [k for k in keys if k not in out]
    return out


def geo_keys(text: str, known_countries: set[str]) -> set[str] | None:
    """Free-text geography ("UK & Europe") -> set of dataset country keys. None = no constraint / unknown."""
    if not text or GLOBAL_GEO.search(text):
        return None
    low = text.lower()
    out: set[str] = set()
    for pat, keys in GEO_SYNONYMS:
        if re.search(pat, low):
            out.update(keys)
    for c in known_countries:
        if len(c) > 3 and re.search(rf"\b{re.escape(c)}\b", low):
            out.add(c)
    return out or None


def stage_keys(text: str) -> set[str]:
    low = (text or "").lower()
    out = set()
    if re.search(r"pre[- ]?seed", low):
        out.add("pre-seed")
    if re.search(r"(?<!pre-)(?<!pre )(?<!pre)\bseed", low):
        out.add("seed")
    for letter in "abc":
        if re.search(rf"series[- ]?{letter}\b", low):
            out.add(f"series-{letter}")
    if re.search(r"growth|late[- ]stage", low):
        out.add("growth")
    if re.search(r"early[- ]stage|very early", low) and not out:
        out.update({"pre-seed", "seed"})
    return out


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def plain(x):
    """Recursively turn numpy scalars/arrays into plain Python (and NaN/inf into None), so the result is strict JSON
    and the backend can unpickle it without numpy."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return [plain(v) for v in x.tolist()]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    return x


def binom_tail(n: int, p: float, k: int) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return float(sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


# ---------------------------------------------------------------------------
# The universe (all 10k companies with their embeddings)
# ---------------------------------------------------------------------------


class Universe:
    def __init__(self, rows: dict[str, dict], emb: np.ndarray, ids: list[str]):
        self.ids = list(ids)
        self.emb = emb.astype(np.float32)
        self.n = len(self.ids)
        self.rows = [rows[i] for i in self.ids]
        self.idx = {cid: i for i, cid in enumerate(self.ids)}
        self.sector = np.array([(r.get("sector") or "") for r in self.rows], dtype=object)
        self.country = np.array([(r.get("country") or "") for r in self.rows], dtype=object)
        # The company's own reported stage only. Never `stage` (partly derived from round names -> label leak).
        self.stage = np.array([(r.get("stage_reported") or "") for r in self.rows], dtype=object)
        self.founded = np.array([_float(r.get("founded_year")) for r in self.rows], dtype=np.float64)
        self.has_profile = np.array([str(r.get("has_profile")) == "1" for r in self.rows])
        self.countries = {c for c in self.country if c}
        self.by_name: dict[str, int] = {}
        self.by_norm: dict[str, int] = {}
        self.by_domain: dict[str, int] = {}
        shared_domains: set[str] = set()  # cdn.prod.website-files.com, fonts.googleapis.com, ... (scraping junk)
        for i, r in enumerate(self.rows):
            self.by_name.setdefault((r.get("name") or "").strip().lower(), i)
            nn = norm_name(r.get("name") or "")
            if nn:
                self.by_norm.setdefault(nn, i)
            d = r.get("domain") or domain_of(r.get("website") or "")
            if d:
                if d in self.by_domain:
                    shared_domains.add(d)
                self.by_domain.setdefault(d, i)
        for d in shared_domains:  # a domain several rows share identifies none of them
            del self.by_domain[d]
        self.by_row = {str(r.get("row_id")): i for i, r in enumerate(self.rows)}
        self.country_label = {r.get("country"): r.get("country_label") for r in self.rows if r.get("country")}
        self.sector_label = {r.get("sector"): r.get("sector_label") for r in self.rows if r.get("sector")}

    def match(self, item) -> int | None:
        """Portfolio entry (id / name / website / row number, or a dict with any of those) -> row index."""
        if isinstance(item, dict):
            for key in ("company_id", "id"):
                v = item.get(key)
                if v and v in self.idx:
                    return self.idx[v]
            for key in ("website", "domain", "url"):
                d = domain_of(item.get(key) or "")
                if d and d in self.by_domain:
                    return self.by_domain[d]
            name = item.get("name") or ""
            return self.match(name) if name else None
        q = str(item or "").strip()
        if not q:
            return None
        if q in self.idx:
            return self.idx[q]
        low = q.lower()
        if low in self.by_name:
            return self.by_name[low]
        if "." in q and " " not in q:
            d = domain_of(q)
            if d in self.by_domain:
                return self.by_domain[d]
        nn = norm_name(q)
        if len(nn) >= 3 and nn in self.by_norm:
            return self.by_norm[nn]
        num = q.lstrip("#")
        if num.isdigit() and str(int(num)) in self.by_row:
            return self.by_row[str(int(num))]
        return None


def _float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# ---------------------------------------------------------------------------
# Fund profile: portfolio vectors + what the Fund DNA says
# ---------------------------------------------------------------------------


class FundProfile:
    """Everything the model knows about a fund. Built either from a live portfolio (score_fit) or from the
    training part of a backtest. `members[j]` is the universe row of portfolio vector j (or None if external)."""

    def __init__(self, U: Universe, vecs: np.ndarray, members: list[int | None], meta: list[dict],
                 thesis_vec: np.ndarray | None, dna_sectors: dict[str, float] | None,
                 dna_geo: set[str] | None, dna_stages: set[str] | None, asof_year: float):
        self.U = U
        self.P = vecs.astype(np.float32) if len(vecs) else np.zeros((0, U.emb.shape[1]), np.float32)
        self.members = members
        self.meta = meta  # [{name, company_id, sector, country, stage, founded}]
        self.m = len(members)
        self.thesis_vec = thesis_vec
        self.dna_sectors = dna_sectors or None
        self.dna_geo = dna_geo
        self.dna_stages = dna_stages or set()
        self.asof_year = asof_year
        self.member_pos = {row: j for j, row in enumerate(members) if row is not None}
        # Portfolio counts (for leave-one-out shares)
        self.sec_count: dict[str, int] = {}
        self.cty_count: dict[str, int] = {}
        self.stg_count: dict[str, int] = {}
        for mm in meta:
            for key, store in (("sector", self.sec_count), ("country", self.cty_count), ("stage", self.stg_count)):
                v = mm.get(key) or ""
                if v:
                    store[v] = store.get(v, 0) + 1
        self.n_sec = sum(self.sec_count.values())
        self.n_cty = sum(self.cty_count.values())


def features(F: FundProfile, vecs: np.ndarray, sector: np.ndarray, country: np.ndarray, stage: np.ndarray,
             founded: np.ndarray, self_pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Raw feature matrix [n, 7] and the similarity matrix [n, m] (self excluded with -inf).

    self_pos[i] = index of row i in the portfolio (leave-one-out), or -1.
    """
    n = len(vecs)
    X = np.zeros((n, len(FEATURES)), np.float64)
    S = vecs @ F.P.T if F.m else np.zeros((n, 0), np.float32)
    S = S.astype(np.float64)
    rows_self = np.where(self_pos >= 0)[0]
    if len(rows_self):
        S[rows_self, self_pos[rows_self]] = -np.inf
    if F.m:
        finite = np.isfinite(S)
        cnt = finite.sum(1)
        smax = np.where(cnt > 0, np.max(np.where(finite, S, -np.inf), axis=1), 0.0)
        smean = np.where(cnt > 0, np.where(finite, S, 0.0).sum(1) / np.maximum(cnt, 1), 0.0)
        X[:, 0] = smax
        X[:, 1] = smean
    if F.thesis_vec is not None:
        X[:, 2] = vecs @ F.thesis_vec
    is_self = self_pos >= 0

    # Sector: leave-one-out share of the portfolio in this sector (normalised so the fund's top sector = 1),
    # averaged with the Fund DNA share when the DNA lists sectors.
    if F.n_sec:
        top = max(F.sec_count.values())
        own = np.array([F.sec_count.get(s, 0) for s in sector], np.float64)
        loo = own - (is_self & (sector != "")).astype(np.float64)
        port = np.where(sector != "", loo / max(top, 1), 0.0)
    else:
        port = None
    if F.dna_sectors:
        dtop = max(F.dna_sectors.values()) or 1.0
        dna = np.array([F.dna_sectors.get(s, 0.0) / dtop for s in sector], np.float64)
    else:
        dna = None
    if port is not None and dna is not None:
        X[:, 3] = 0.5 * port + 0.5 * dna
    elif port is not None:
        X[:, 3] = port
    elif dna is not None:
        X[:, 3] = dna

    # Stage: 1 = a stage the fund backs, 0 = a different stage, 0.5 = unknown (95% of rows)
    # The Fund DNA's stated stages win; otherwise the stages its portfolio companies report, leave-one-out
    # (a portfolio company's own stage must not make its stage "one the fund backs").
    if F.dna_stages:
        X[:, 4] = np.array([0.5 if not s else (1.0 if s in F.dna_stages else 0.0) for s in stage])
    elif F.stg_count:
        X[:, 4] = np.array([0.5 if not s else (1.0 if F.stg_count.get(s, 0) - int(own) >= 1 else 0.0)
                            for s, own in zip(stage, is_self)])
    else:
        X[:, 4] = 0.5

    # Geo: leave-one-out share of the portfolio in this country (top country = 1), averaged with DNA geo match.
    if F.n_cty:
        top = max(F.cty_count.values())
        own = np.array([F.cty_count.get(c, 0) for c in country], np.float64)
        loo = own - (is_self & (country != "")).astype(np.float64)
        gport = np.where(country != "", loo / max(top, 1), 0.0)
    else:
        gport = None
    gdna = np.array([1.0 if c in F.dna_geo else 0.0 for c in country]) if F.dna_geo else None
    if gport is not None and gdna is not None:
        X[:, 5] = 0.5 * gport + 0.5 * gdna
    elif gport is not None:
        X[:, 5] = gport
    elif gdna is not None:
        X[:, 5] = gdna

    # Recency: 1 = founded this year (or later than the as-of date), 0 = 20+ years before; unknown = 0.5
    age = F.asof_year - founded
    X[:, 6] = np.where(np.isnan(founded), 0.5, np.clip(1.0 - age / 20.0, 0.0, 1.0))
    return X, S


def universe_features(F: FundProfile) -> tuple[np.ndarray, np.ndarray]:
    U = F.U
    self_pos = np.full(U.n, -1, np.int64)
    for row, j in F.member_pos.items():
        self_pos[row] = j
    return features(F, U.emb, U.sector, U.country, U.stage, U.founded, self_pos)


def external_features(F: FundProfile) -> np.ndarray:
    """Leave-one-out features for portfolio companies that are not in the dataset (embedded from their text)."""
    ext = [j for j, row in enumerate(F.members) if row is None]
    if not ext:
        return np.zeros((0, len(FEATURES)))
    meta = [F.meta[j] for j in ext]
    X, _ = features(
        F, F.P[ext],
        np.array([m.get("sector") or "" for m in meta], dtype=object),
        np.array([m.get("country") or "" for m in meta], dtype=object),
        np.array([m.get("stage") or "" for m in meta], dtype=object),
        np.array([_float(m.get("founded")) for m in meta]),
        np.array(ext, np.int64),
    )
    return X


# ---------------------------------------------------------------------------
# The model: standardise, logistic regression, contributions
# ---------------------------------------------------------------------------


class FitModel:
    def __init__(self, mu: np.ndarray, sd: np.ndarray, w: np.ndarray, b: float, method: str,
                 n_pos: int, n_neg: int, active: np.ndarray):
        self.mu, self.sd, self.w, self.b = mu, sd, w, b
        self.method, self.n_pos, self.n_neg = method, n_pos, n_neg
        self.active = active
        self.q50 = 0.0
        self.ref = 1.0

    def z(self, X: np.ndarray) -> np.ndarray:
        return np.where(self.active, (X - self.mu) / self.sd, 0.0)

    def logit(self, X: np.ndarray) -> np.ndarray:
        return self.z(X) @ self.w + self.b

    def calibrate(self, logit_universe: np.ndarray, logit_pos: np.ndarray | None) -> None:
        """Anchors for the 0..100 fit: universe median -> 30, a typical portfolio company -> 90."""
        self.q50 = float(np.median(logit_universe))
        floor = float(np.quantile(logit_universe, 0.99))
        ref = float(np.median(logit_pos)) if logit_pos is not None and len(logit_pos) else float(
            np.quantile(logit_universe, 0.995))
        self.ref = max(ref, floor)
        if self.ref - self.q50 < 1e-6:
            self.ref = self.q50 + 1.0

    def fit_score(self, logit: np.ndarray) -> np.ndarray:
        """0..100 (integer). 90 = looks as much like the fund as a typical company it already owns,
        30 = an average company in the dataset. Above 90 it bends towards 99, below 30 towards 0."""
        u = (logit - self.q50) / (self.ref - self.q50)
        fit = np.where(u <= 0, 30.0 * np.exp(2.0 * np.minimum(u, 0)),
                       np.where(u <= 1, 30.0 + 60.0 * u, 90.0 + 9.0 * (1.0 - np.exp(-1.0 * (u - 1.0)))))
        return np.clip(np.round(fit), 0, 99).astype(int)

    def weight_shares(self) -> list[dict]:
        """Share of the score per UI part (|standardised coefficient|), for 'What the score depends on'."""
        agg: dict[str, float] = {p: 0.0 for p in PARTS}
        sign: dict[str, float] = {p: 0.0 for p in PARTS}
        for k, f in enumerate(FEATURES):
            if not self.active[k]:
                continue
            agg[PART_OF[f]] += abs(float(self.w[k]))
            sign[PART_OF[f]] += float(self.w[k])
        total = sum(agg.values()) or 1.0
        out = []
        for p in PARTS:
            if agg[p] <= 1e-6:
                continue
            label = WEIGHT_LABEL[p]
            if sign[p] < 0:
                label = WEIGHT_LABEL_NEG.get(p, f"{label} (counts against)")
            out.append({"label": label, "share": agg[p] / total, "part": p,
                        "direction": "for" if sign[p] >= 0 else "against"})
        out.sort(key=lambda d: -d["share"])
        for d in out:  # round to 2 dp and make them sum to exactly 1
            d["share"] = round(d["share"], 2)
        if out:
            out[0]["share"] = round(out[0]["share"] + 1.0 - sum(d["share"] for d in out), 2)
        out = [d for d in out if d["share"] > 0]
        for i, d in enumerate(out):
            d["color"] = COLORS[i % len(COLORS)]
        return out

    def coefficients(self) -> list[dict]:
        return [{"feature": f, "coef": round(float(self.w[k]), 4), "used": bool(self.active[k])}
                for k, f in enumerate(FEATURES)]


def _logreg(Z: np.ndarray, y: np.ndarray, sw: np.ndarray, l2: float, free: np.ndarray) -> tuple[np.ndarray, float]:
    """L2-regularised, weighted logistic regression where every weight is >= 0 except where `free` is True.
    "More like the portfolio / more in the fund's sector" can then only ever raise the score, which keeps the
    explanations honest with few portfolio companies. Solved with scipy's L-BFGS-B (scipy ships with sklearn)."""
    from scipy.optimize import minimize
    from scipy.special import expit

    p = Z.shape[1]
    sgn = np.where(y > 0, 1.0, -1.0)

    def f(theta):
        w, b = theta[:p], theta[p]
        ys = sgn * (Z @ w + b)
        loss = float((sw * np.logaddexp(0.0, -ys)).sum() + 0.5 * l2 * (w @ w))
        g = -sw * sgn * expit(-ys)
        return loss, np.r_[Z.T @ g + l2 * w, g.sum()]

    bounds = [(None, None) if free[k] else (0.0, None) for k in range(p)] + [(None, None)]
    res = minimize(f, np.zeros(p + 1), jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
    return res.x[:p], float(res.x[p])


def train(Xu: np.ndarray, pos_rows: list[int], Xext: np.ndarray, exclude_neg: set[int], seed: str,
          n_neg: int = N_NEGATIVES, drop: tuple[str, ...] = ("recency",), early_stage: bool = False,
          free: tuple[str, ...] = ()) -> FitModel:
    """Per-fund logistic regression. Positives: portfolio (in-dataset rows + external), negatives: a fixed-seed
    random sample of other rows. Standardisation uses the whole universe.

    Recency is NOT learned by default: we only know a company's age today, not its age when the fund invested,
    so a learned weight just says "portfolio companies are older than brand-new register filings". Instead, when
    the Fund DNA says the fund backs pre-seed / seed, recency gets a small fixed weight (RECENCY_PRIOR).

    Class weights: each positive counts 1, the negatives together count as much as the positives, and the L2
    penalty is 1. So a fund with 6 known companies gets a heavily regularised model, one with 200 a confident one.
    """
    mu = Xu.mean(0)
    sd = Xu.std(0)
    usable = sd > 1e-9
    sd = np.where(usable, sd, 1.0)
    learn = usable & np.array([f not in drop for f in FEATURES])
    Xpos = np.vstack([Xu[pos_rows], Xext]) if len(Xext) else Xu[pos_rows]
    n_pos = len(Xpos)

    rng = np.random.default_rng(int(stable_hash(seed)[:8], 16))
    pool = np.array([i for i in range(len(Xu)) if i not in exclude_neg])
    neg = rng.choice(pool, size=min(n_neg, len(pool)), replace=False)

    w = np.zeros(len(FEATURES))
    if n_pos >= MIN_POSITIVES:
        Z = np.vstack([(Xpos - mu) / sd, (Xu[neg] - mu) / sd])
        Z = np.where(learn, Z, 0.0)
        y = np.r_[np.ones(n_pos), np.zeros(len(neg))]
        sw = np.r_[np.ones(n_pos), np.full(len(neg), n_pos / len(neg))]
        free_mask = np.array([f in free for f in FEATURES])
        w, b = _logreg(Z, y, sw, 1.0, free_mask)
        # Shrink towards the default weights when the fund has few known companies (a = 0.33 at 5, 0.96 at 230),
        # so the written thesis and location still count for a small portfolio.
        a = n_pos / (n_pos + PRIOR_STRENGTH)
        prior = np.array([PRIOR_WEIGHTS[f] for f in FEATURES])
        w = (a * w + (1 - a) * prior) * learn
        method = "logistic regression" if a >= 0.9 else "logistic regression, blended with default weights"
    else:
        w = np.array([PRIOR_WEIGHTS[f] for f in FEATURES]) * learn
        b = 0.0
        method = "fixed weights (too few portfolio companies to learn from)"
    k_rec = FEATURES.index("recency")
    if "recency" in drop and early_stage and usable[k_rec]:
        w[k_rec] = RECENCY_PRIOR
    active = usable & (np.abs(w) > 1e-6)
    model = FitModel(mu, sd, w, b, method, n_pos, len(neg), active)
    model.calibrate(model.logit(Xu), model.logit(Xpos) if n_pos >= MIN_POSITIVES else None)
    return model


# ---------------------------------------------------------------------------
# Plain-English explanation of one candidate
# ---------------------------------------------------------------------------


def _band(v: float, hi: float, mid: float) -> int:
    return 2 if v >= hi else (1 if v >= mid else 0)


def explain(F: FundProfile, model: FitModel, X: np.ndarray, i: int, srow: np.ndarray, scale: dict,
            sector_key: str, country_key: str, stage_key: str, founded: float) -> tuple[list[dict], list[dict]]:
    U = F.U
    z = model.z(X[i:i + 1])[0]
    impact = z * model.w
    order = np.argsort(-srow) if F.m else np.array([], int)
    nearest = []
    for j in order[:3]:
        if not np.isfinite(srow[j]):
            continue
        mm = F.meta[j]
        nearest.append({"company_id": mm.get("company_id"), "name": mm.get("name"), "score": round(float(srow[j]), 4)})
    near_name = nearest[0]["name"] if nearest else None

    def scaled(f: str, v: float) -> float:
        lo, hi = scale[f]
        return float(np.clip((v - lo) / (hi - lo), 0, 1)) if hi > lo else 0.5

    out = []
    for k, f in enumerate(FEATURES):
        if not model.active[k]:
            continue
        raw = float(X[i, k])
        if f in ("sim_max", "sim_mean", "thesis"):
            value = scaled(f, raw)
        else:
            value = float(np.clip(raw, 0, 1))
        b = _band(value, 0.75, 0.45)
        if f == "sim_max":
            label = (["A bit like {n}", "Like {n}", "Very like {n}"][b]).format(n=near_name) if near_name else \
                "Not much like anything they own"
        elif f == "sim_mean":
            label = ["Unlike most of the portfolio", "Fairly close to the portfolio", "Close to the portfolio as a whole"][b]
        elif f == "thesis":
            label = ["Off the written thesis", "Partly matches the thesis", "Matches the thesis"][b]
        elif f == "sector":
            name = U.sector_label.get(sector_key) or sector_key
            label = f"Sector unknown" if not sector_key else \
                [f"Sector they rarely back ({name})", f"Sector they sometimes back ({name})", f"Right sector ({name})"][b]
        elif f == "stage":
            name = STAGE_LABEL.get(stage_key, stage_key)
            label = "Stage unknown" if not stage_key else (f"Right stage ({name})" if raw >= 1 else f"Different stage ({name})")
        elif f == "geo":
            name = U.country_label.get(country_key) or country_key
            label = "Location unknown" if not country_key else \
                [f"Outside their usual area ({name})", f"Area they sometimes back ({name})", f"Right location ({name})"][b]
        else:  # recency
            label = "Founding year unknown" if np.isnan(founded) else \
                (f"Founded recently ({int(founded)})" if value >= 0.85 else f"Founded in {int(founded)}")
        out.append({
            "feature": f,
            "part": PART_OF[f],
            "label": label,
            "value": round(value, 3),
            "raw": round(raw, 4),
            "impact": round(float(impact[k]), 4),
        })
    out.sort(key=lambda d: -d["impact"])
    # One 0..1 bar per UI part (contract FitPart labels), only for parts the model actually uses.
    parts: dict[str, float] = {}
    for p in FIT_PART_ORDER:
        vals = [c["value"] for c in out if c["part"] == p and c["feature"] != "sim_mean"]
        vals = vals or [c["value"] for c in out if c["part"] == p]
        if vals:
            parts[p] = round(max(vals), 2)
    return out, nearest, parts


def sim_scale(X: np.ndarray) -> dict:
    """Bar scaling for similarity features: universe 50th percentile -> 0, 99.9th -> 1."""
    return {f: (float(np.quantile(X[:, k], 0.5)), float(np.quantile(X[:, k], 0.999)))
            for k, f in enumerate(FEATURES) if f in ("sim_max", "sim_mean", "thesis")}


# ---------------------------------------------------------------------------
# Fund DNA parsing
# ---------------------------------------------------------------------------


def dna_parts(fund_dna: dict | None, U: Universe) -> tuple[str, dict[str, float], set[str] | None, set[str]]:
    """-> (thesis text, sector shares by key, geo country keys or None, stage keys)."""
    d = fund_dna or {}
    bits = []
    for key in ("thesis", "summary"):
        if d.get(key):
            bits.append(str(d[key]).strip().rstrip("."))
    themes = [str(t) for t in (d.get("themes") or []) if t]
    if themes:
        bits.append("; ".join(themes))
    sector_names = []
    shares: dict[str, float] = {}
    for s in d.get("sectors") or []:
        name = s.get("name") if isinstance(s, dict) else str(s)
        share = float(s.get("share") or 0) if isinstance(s, dict) else 0.0
        if not name:
            continue
        sector_names.append(name)
        for k in sector_keys(name):
            shares[k] = max(shares.get(k, 0.0), share or 1.0)
    if sector_names and len(bits) < 2:
        bits.append("Sectors: " + ", ".join(sector_names))
    thesis = ". ".join(bits)
    geo = geo_keys(str(d.get("geo") or ""), U.countries)
    stages = stage_keys(str(d.get("stage") or ""))
    return thesis, shares, geo, stages


# ---------------------------------------------------------------------------
# Ranking helpers for the backtest
# ---------------------------------------------------------------------------


def ranks_of(scores: np.ndarray, cand: np.ndarray, targets: list[int]) -> list[int]:
    """1-based rank of each target among candidate rows (ties broken pessimistically)."""
    cs = scores[cand]
    out = []
    for t in targets:
        out.append(int((cs > scores[t]).sum() + (cs == scores[t]).sum()))
    return out


def hit_table(ranks: list[int], n_cand: int) -> dict:
    tops = {}
    for pct in (1, 5, 10):
        cut = math.ceil(n_cand * pct / 100)
        tops[f"top_{pct}pct"] = {"cutoff_rank": cut, "found": int(sum(r <= cut for r in ranks))}
    recall = {str(k): int(sum(r <= k for r in ranks)) for k in (10, 50, 100, 500)}
    return {
        **tops,
        "recall_at_k": recall,
        "median_rank": float(np.median(ranks)) if ranks else None,
        "mean_percentile": round(float(np.mean([r / n_cand for r in ranks])) * 100, 1) if ranks else None,
        "ranks": sorted(ranks),
    }


def random_table(n_held: int, n_cand: int) -> dict:
    out = {}
    for pct in (1, 5, 10):
        cut = math.ceil(n_cand * pct / 100)
        out[f"top_{pct}pct"] = {"cutoff_rank": cut, "expected_found": round(n_held * cut / n_cand, 2)}
    out["recall_at_k"] = {str(k): round(n_held * k / n_cand, 2) for k in (10, 50, 100, 500)}
    out["median_rank"] = (n_cand + 1) / 2
    return out


def keyword_scores(texts: list[str], train_rows: list[int], thesis: str = "") -> tuple[dict[str, np.ndarray], dict]:
    """TF-IDF keyword baseline: similarity of each company's text to the training portfolio's texts.
    'centroid' = cosine to the average portfolio vector; 'max' = best match to any one portfolio company.

    Also returns the keyword versions of the model's three text features (sim_max, sim_mean, thesis), leave-one-out
    for the training rows exactly like the embedding features, so the baseline can be given the same model and the
    same sector / stage / location features ('plus_structure' in run_backtest)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=2, ngram_range=(1, 2), max_features=100_000)
    T = vec.fit_transform(texts)  # unsupervised: fitted on all company texts, no labels
    P = T[train_rows]
    centroid = np.asarray(P.mean(axis=0)).ravel()
    nrm = np.linalg.norm(centroid) or 1.0
    cen = np.asarray(T @ (centroid / nrm)).ravel()
    S = (T @ P.T).toarray()
    # Ranking: training rows are never candidates, so their self-match does not matter here.
    scores = {"centroid": cen, "max": S.max(axis=1)}
    # Features: leave-one-out for the training rows (same rule as fitcore.features).
    m = len(train_rows)
    finite = np.ones_like(S, dtype=bool)
    finite[np.asarray(train_rows), np.arange(m)] = False
    cnt = finite.sum(1)
    feats = {
        "sim_max": np.where(cnt > 0, np.max(np.where(finite, S, -np.inf), axis=1), 0.0),
        "sim_mean": np.where(finite, S, 0.0).sum(1) / np.maximum(cnt, 1),
        "thesis": np.asarray((T @ vec.transform([thesis]).T).todense()).ravel() if thesis else None,
    }
    return scores, feats


# ---------------------------------------------------------------------------
# Entry points (called by modal_app.py; `embed` is a callable(texts, query: bool) -> np.ndarray [n, d])
# ---------------------------------------------------------------------------


def _row_meta(U: Universe, i: int) -> dict:
    r = U.rows[i]
    return {"name": r.get("name"), "company_id": r.get("id"), "sector": U.sector[i], "country": U.country[i],
            "stage": U.stage[i], "founded": U.founded[i]}


def company_dict(row: dict) -> dict:
    """Company-shaped dict (backend/app/models.py Company) plus a few extras."""
    def _int(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    return {
        "company_id": row["id"],
        "id": row["id"],
        "row_id": _int(row.get("row_id")),
        "name": row["name"],
        "one_liner": row.get("one_liner") or "",
        "sector": row.get("sector_label") or "",
        "sector_key": row.get("sector") or None,
        "stage": row.get("stage_label") or "",
        "country": row.get("country_label") or None,
        "founded": _int(row.get("founded_year")),
        "website": row.get("website") or None,
        "domain": row.get("domain") or None,
    }


def _external_meta(U: Universe, item: dict) -> dict:
    label_to_country = {v.lower(): k for k, v in U.country_label.items() if v}
    c = str(item.get("country") or "").strip().lower()
    country = c if c in U.countries else label_to_country.get(c, "")
    secs = sector_keys(str(item.get("sector") or ""))
    stg = stage_keys(str(item.get("stage") or ""))
    return {"name": item.get("name") or item.get("website") or "Unnamed", "company_id": None,
            "sector": secs[0] if secs else "", "country": country,
            "stage": sorted(stg, key=STAGE_KEYS.index)[0] if stg else "", "founded": _float(item.get("founded"))}


def _item_text(item: dict) -> str:
    parts = [item.get("name") or ""]
    for key in ("one_liner", "description", "summary", "what_they_do", "text"):
        if item.get(key):
            parts.append(str(item[key]))
    return ". ".join(p.strip().rstrip(".") for p in parts if p).strip()


def run_score_fit(U: Universe, fund_dna: dict | None, portfolio: list, k: int, embed, fund_id: str | None = None,
                  asof_year: float | None = None) -> dict:
    t0 = time.time()
    k = max(1, min(int(k or 50), 500))
    rows: list[int] = []
    matched, external, unmatched = [], [], []
    ext_items: list[dict] = []
    for item in portfolio or []:
        i = U.match(item)
        label = item.get("name") if isinstance(item, dict) else str(item)
        if i is not None:
            if i not in rows:
                rows.append(i)
                matched.append({"input": label, "company_id": U.ids[i], "name": U.rows[i]["name"]})
            continue
        if isinstance(item, dict) and len(_item_text(item)) > len(item.get("name") or "") + 10:
            ext_items.append(item)
            external.append({"input": label, "name": item.get("name")})
        else:
            unmatched.append(label)

    thesis, dna_sec, dna_geo, dna_stg = dna_parts(fund_dna, U)
    dim = U.emb.shape[1]
    ext_vecs = np.asarray(embed([_item_text(x) for x in ext_items], False)) if ext_items else np.zeros((0, dim))
    vecs = np.vstack([U.emb[rows].reshape(-1, dim), ext_vecs.reshape(-1, dim)])
    members = rows + [None] * len(ext_items)
    meta = [_row_meta(U, i) for i in rows] + [_external_meta(U, x) for x in ext_items]
    tvec = np.asarray(embed([thesis], True))[0] if thesis else None
    year = asof_year or float(datetime.now(timezone.utc).year)
    F = FundProfile(U, vecs, members, meta, tvec, dna_sec, dna_geo, dna_stg, year)

    t1 = time.time()
    Xu, S = universe_features(F)
    Xext = external_features(F)
    seed = fund_id or "|".join(sorted(str(m["name"] or "") for m in meta))
    model = train(Xu, rows, Xext, exclude_neg=set(rows), seed=seed, early_stage=bool(dna_stg & EARLY_STAGES))
    logit = model.logit(Xu)
    fit = model.fit_score(logit)
    score_secs = time.time() - t1
    score = logit.copy()
    score[rows] = -np.inf  # never recommend what they already own
    top = np.argsort(-score)[:k]
    scale = sim_scale(Xu)
    results = []
    for rank, i in enumerate(top, start=1):
        contribs, nearest, parts = explain(F, model, Xu, int(i), S[i], scale, U.sector[i], U.country[i], U.stage[i],
                                           U.founded[i])
        d = company_dict(U.rows[i])
        d.update(
            rank=rank,
            fit=int(fit[i]),  # 0..99, the number the UI shows
            score=round(int(fit[i]) / 100.0, 2),  # 0..1 (= fit / 100, like the backend's offline fallback)
            # (a sigmoid of the logit saturates at 1.0 for every top result, so it is not used)
            logit=round(float(logit[i]), 4),
            parts=parts,  # {"Like the portfolio": 0.93, "Right stage": 1.0, "Right location": 0.8, ...}
            fit_parts=[{"label": p, "value": v} for p, v in parts.items()],  # contract FitPart list
            like=next((n["company_id"] for n in nearest if n.get("company_id")), None),  # closest portfolio company id
            contributions=contribs,
            nearest_portfolio=nearest,
        )
        results.append(d)
    weights = model.weight_shares()
    feature_weights = [{"label": w["label"], "share": w["share"], "color": w["color"]} for w in weights]
    return plain({
        "fund_id": fund_id,
        "k": k,
        "dataset_size": U.n,
        "n_scored": U.n,
        "model": MODEL_NAME,
        "feature_weights": feature_weights,
        "results": results,
        "portfolio": {"matched": matched, "external": external, "unmatched": unmatched},
        "thesis_text": thesis or None,
        "model_info": {
            "method": model.method,
            "n_positive": model.n_pos,
            "n_negative": model.n_neg,
            "coefficients": model.coefficients(),
            "feature_weights": feature_weights,
            "fit_note": "90 = looks as much like this fund as a typical company it already owns.",
            "never_used": NEVER_USED,
        },
        "score_seconds": round(score_secs, 3),
        "total_seconds": round(time.time() - t0, 3),
    })


def _date_year(d: str) -> float:
    y, m = int(d[:4]), int(d[5:7] or 1)
    return y + (m - 1) / 12.0


def _date_label(now: datetime) -> str:
    return now.strftime("%d %b %Y").lstrip("0")


def _model_card(n_train: int | None, fund_name: str | None = None, n: int = 10000) -> dict:
    data = f"{n:,} startups"
    if n_train:
        data += f", {n_train} earlier {fund_name} deals"
    return {
        "trained_on": "Modal",
        "data": data,
        "method": "Text match + scoring model",
        "retrains": "Every time the analyst runs",
        "never_used": NEVER_USED,
    }


def _not_enough_message(name: str, info: dict, min_dated: int) -> str:
    n = info.get("dated_deals", 0)
    msg = f"Not enough history for this fund. The dataset has {n} dated {name} deal{'' if n == 1 else 's'}"
    fam = info.get("family")
    if fam and fam.get("dated", 0) != n:
        msg += f" ({fam['dated']} counting related funds)"
    return msg + f", and a fair test needs at least {min_dated}."


def _not_enough(slug: str, name: str, info: dict, min_dated: int, n: int) -> dict:
    return plain({
        "fund_id": slug,
        "enough_history": False,
        "held_out": 0,
        "top_percent": 5,
        "methods": [],
        "feature_weights": [],
        "model_card": _model_card(None, n=n),
        "score_seconds": 0.0,
        "trained_at": iso_now(),
        "trained_label": _date_label(datetime.now(timezone.utc)),
        "status": "not_enough_history",
        "details": {
            "fund_name": name,
            **info,
            "needed_dated_deals": min_dated,
            "message": _not_enough_message(name, info, min_dated),
        },
    })


FUND_CAVEATS = {
    "y-combinator": [
        "The dataset has no Y Combinator deal dates, so the founding year stands in for the deal date. "
        "The held-out companies are the most recently founded ones.",
    ],
    "european-commission": [
        "The European Commission gives research grants; it is not a venture fund. Its list includes "
        "large corporates and research consultancies.",
    ],
}
GENERAL_CAVEAT = ("Most rows in the dataset only have a one-line description from a company register, while portfolio "
                  "companies usually have a full website profile. That alone makes them easier to find. "
                  "The 'website profile only' check ranks only companies that have a profile, which removes most "
                  "of that advantage.")
DESIGN_CAVEAT = ("Some model choices (recency is not learned; weights cannot be negative) were made after looking at "
                 "earlier test runs on these same funds, so the numbers are slightly optimistic.")
MIN_DATED = 25  # same rule as backend/app/modal_client.py MIN_DATED_DEALS
MIN_HELD_OUT = 10  # same rule as backend/app/modal_client.py MIN_HELD_OUT
MIN_TRAIN = 10


def fund_history(U: Universe, investors: dict, index: dict, fund: str) -> tuple[str, str, list[dict], dict]:
    """-> (slug, display name, in-dataset deals, info dict). No embeddings needed."""
    slug = slugify(fund)
    name = ((index.get("investors") or {}).get(slug) or {}).get("name") or fund
    deals = [d for d in investors.get(slug, []) if d.get("company_id") in U.idx]
    info = {"companies_in_dataset": len(deals), "dated_deals": sum(1 for d in deals if d.get("date"))}
    fam = (index.get("fund_families") or {}).get(slug)
    if fam:
        fam_deals = {d["company_id"]: d for m in fam.get("members", []) for d in investors.get(m, [])
                     if d.get("company_id") in U.idx}
        info["family"] = {
            "members": fam.get("members"),
            "companies": len(fam_deals),
            "dated": sum(1 for d in fam_deals.values() if d.get("date")),
            "companies_list": [{"company_id": c, "name": U.rows[U.idx[c]]["name"], "date": d.get("date")}
                               for c, d in fam_deals.items()],
        }
    return slug, name, deals, info


def run_backtest(U: Universe, investors: dict, index: dict, fund: str, embed, texts: list[str],
                 n_hold_max: int = 20, min_dated: int = MIN_DATED) -> dict:
    """Time-ordered backtest. Leakage rules (audited 2026-10-15):

    - Labels come only from investors.json. investors / investor_ids / discovery_source / round data are never features
      (Universe does not even load them) and the fund's name never reaches the thesis text.
    - Split: sort the dated deals (sha1 tie-break), hold out the last n_hold. Training uses only deals dated strictly
      BEFORE the first held-out date ("purge"): deals that share that date but were not held out (YC: same founding
      year) are dropped from training and from the candidates, so no same-cohort company teaches the model.
    - Candidates = every row except the training deals, the purged deals and the fund's undated deals (neither train
      nor test). Model, keyword and random are scored on exactly the same candidates and held-out rows.
    - Negatives = a seeded random sample of every row that is not a training deal. Held-out, purged and undated rows
      are unlabelled at training time, so they can be drawn as negatives (this can only hurt the model).
    - Unsupervised parts (embeddings, TF-IDF vocabulary, feature standardisation) see all 10k texts, no labels.
    """
    slug, name, deals, info = fund_history(U, investors, index, fund)
    dated = [d for d in deals if d.get("date")]
    if len(dated) < min_dated:
        return _not_enough(slug, name, info, min_dated, U.n)

    t_start = time.time()
    order = sorted(dated, key=lambda d: (d["date"], stable_hash(d["company_id"])))  # fixed tie-break
    n_hold = min(n_hold_max, max(MIN_HELD_OUT, len(order) // 3))
    held_deals = order[-n_hold:]
    first_test = held_deals[0]["date"]
    train_deals = [d for d in order[:-n_hold] if d["date"] < first_test]
    purged_deals = [d for d in order[:-n_hold] if d["date"] >= first_test]
    if len(train_deals) < MIN_TRAIN:
        return _not_enough(slug, name, info, min_dated, U.n)
    train_rows = [U.idx[d["company_id"]] for d in train_deals]
    held_rows = [U.idx[d["company_id"]] for d in held_deals]
    purged_rows = [U.idx[d["company_id"]] for d in purged_deals]
    undated_rows = [U.idx[d["company_id"]] for d in deals if not d.get("date")]
    assert not set(train_rows) & set(held_rows), "held-out company in the training set"
    cutoff = train_deals[-1]["date"]
    excluded = set(train_rows) | set(purged_rows) | set(undated_rows)
    cand = np.array([i for i in range(U.n) if i not in excluded])
    n_cand = len(cand)
    assert set(held_rows) <= set(cand.tolist()), "a held-out company is not a candidate"

    # Fund profile from the training deals only. The thesis text is written from their top sectors and countries.
    meta = [_row_meta(U, i) for i in train_rows]
    sec: dict[str, int] = {}
    cty: dict[str, int] = {}
    for m in meta:
        if m["sector"]:
            sec[m["sector"]] = sec.get(m["sector"], 0) + 1
        if m["country"]:
            cty[m["country"]] = cty.get(m["country"], 0) + 1
    top_sec = [U.sector_label.get(s, s) for s, _ in sorted(sec.items(), key=lambda kv: -kv[1])[:3]]
    top_cty = [U.country_label.get(c, c) for c, _ in sorted(cty.items(), key=lambda kv: -kv[1])[:2]]
    thesis = f"{', '.join(top_sec)} startups in {' and '.join(top_cty)}" if top_sec and top_cty else ""
    tvec = np.asarray(embed([thesis], True))[0] if thesis else None
    neg_excl = set(train_rows)
    no_ext = np.zeros((0, len(FEATURES)))

    def fit_and_rank(swap=None, **kw):
        F = FundProfile(U, U.emb[train_rows], list(train_rows), meta, tvec, None, None, set(), _date_year(cutoff))
        t0 = time.time()
        Xu, _S = universe_features(F)
        if swap is not None:  # same structured features, text features swapped in by the caller
            swap(Xu)
        model = train(Xu, train_rows, no_ext, exclude_neg=neg_excl, seed=slug, **kw)
        score = model.logit(Xu)
        return Xu, model, score, time.time() - t0

    Xu, model, score, score_secs = fit_and_rank()
    r_model = ranks_of(score, cand, held_rows)

    # Keyword baselines. Same texts, same training deals, same candidates.
    kw, kw_feats = keyword_scores(texts, train_rows, thesis)

    def swap_text_features(X):
        X[:, FEATURES.index("sim_max")] = kw_feats["sim_max"]
        X[:, FEATURES.index("sim_mean")] = kw_feats["sim_mean"]
        if kw_feats["thesis"] is not None:
            X[:, FEATURES.index("thesis")] = kw_feats["thesis"]

    # "plus_structure" = the full Bellwether model with TF-IDF in place of the embeddings: the baseline gets exactly
    # the same information (sector, stage, location, thesis, training deals); only the text representation differs.
    _, _, kw["plus_structure"], _ = fit_and_rank(swap=swap_text_features)
    kw_tables = {v: hit_table(ranks_of(s, cand, held_rows), n_cand) for v, s in kw.items()}
    # Report the strongest keyword variant, picked on the held-out companies (this favours the baseline, not us).
    kw_best = max(kw_tables, key=lambda v: (kw_tables[v]["top_5pct"]["found"], -kw_tables[v]["median_rank"]))
    # Ablation: let the model learn a recency weight of either sign (what the README warns against).
    _, _, score_rec, _ = fit_and_rank(drop=(), free=("recency",))
    t_model = hit_table(r_model, n_cand)
    t_kw = kw_tables[kw_best]
    t_rand = random_table(n_hold, n_cand)

    # Control: rank only companies with a website profile (removes the "rich text vs register stub" shortcut).
    cand_p = np.array([i for i in cand if U.has_profile[i]])
    held_p = [i for i in held_rows if U.has_profile[i]]
    control = {
        "candidates": len(cand_p),
        "held_out_with_profile": len(held_p),
        "model": hit_table(ranks_of(score, cand_p, held_p), len(cand_p)) if held_p else None,
        "keyword": hit_table(ranks_of(kw[kw_best], cand_p, held_p), len(cand_p)) if held_p else None,
        "keyword_variants": ({v: hit_table(ranks_of(s, cand_p, held_p), len(cand_p)) for v, s in kw.items()}
                             if held_p else None),
        "random": random_table(len(held_p), len(cand_p)) if held_p else None,
    }

    found5 = t_model["top_5pct"]["found"]
    p5 = t_model["top_5pct"]["cutoff_rank"] / n_cand
    weights = model.weight_shares()
    held_detail = [{"company_id": d["company_id"], "name": U.rows[i]["name"], "date": d["date"],
                    "date_source": d.get("date_source"), "rank": r, "top_percent": round(100 * r / n_cand, 1)}
                   for d, i, r in zip(held_deals, held_rows, r_model)]
    return plain({
        "fund_id": slug,
        "enough_history": True,
        "held_out": n_hold,
        "top_percent": 5,
        "methods": [
            {"label": "Bellwether model", "found": found5, "total": n_hold},
            {"label": "Keyword search", "found": t_kw["top_5pct"]["found"], "total": n_hold},
            {"label": "Random pick", "found": int(round(t_rand["top_5pct"]["expected_found"])), "total": n_hold},
        ],
        "feature_weights": [{"label": w["label"], "share": w["share"], "color": w["color"]} for w in weights],
        "model_card": _model_card(len(train_rows), name, U.n),
        "score_seconds": round(score_secs, 2),
        "trained_at": iso_now(),
        "trained_label": _date_label(datetime.now(timezone.utc)),
        "status": "ok",
        "details": {
            "fund_name": name,
            **info,
            "train_deals": len(train_rows),
            "purged_same_date": len(purged_rows),
            "undated_excluded": len(undated_rows),
            "cutoff_date": cutoff,
            "first_test_date": first_test,
            "candidates": n_cand,
            "thesis_text": thesis,
            "held_out_companies": held_detail,
            "metrics": {
                "model": t_model,
                "keyword": {**t_kw, "variant": kw_best},
                "keyword_variants": kw_tables,
                "random": t_rand,
                "embedding_only": hit_table(ranks_of(Xu[:, 0], cand, held_rows), n_cand),
                "model_with_learned_recency": hit_table(ranks_of(score_rec, cand, held_rows), n_cand),
                "website_profile_only": control,
            },
            "p_value_vs_random_top5": round(binom_tail(n_hold, p5, found5), 6),
            "model": {"method": model.method, "n_positive": model.n_pos, "n_negative": model.n_neg,
                      "coefficients": model.coefficients(), "feature_weights_full": weights},
            "never_features": ["discovery_source", "investors", "investor_ids", "funding rounds, amounts and dates",
                               "stage when it comes from a round name", "the fund name",
                               "legal-form endings in company names (Ltd, GmbH, S.L.)"],
            "split_rules": [
                "Training uses only deals dated before the first held-out deal; same-date deals that were not held "
                "out are dropped from training and from the candidates.",
                "Negatives can include held-out companies (they are unlabelled when the model is trained).",
                "Keyword plus_structure uses the same model and the same sector, stage and location features, with "
                "TF-IDF instead of embeddings. The strongest keyword variant is reported.",
            ],
            "caveats": FUND_CAVEATS.get(slug, []) + [GENERAL_CAVEAT, DESIGN_CAVEAT],
            "total_seconds": round(time.time() - t_start, 2),
        },
    })
