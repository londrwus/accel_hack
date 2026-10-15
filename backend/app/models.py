"""Shared data shapes for Bellwether.

Mirror of frontend/src/lib/types.ts. Keep the two files IDENTICAL in shape.
Field names are snake_case on both sides. See shared/contract.md.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums (string literals)
# ---------------------------------------------------------------------------

SignalKind = Literal["timing", "strength", "info", "risk"]
# timing = gold (e.g. "Raising now"), strength = sage ("Revenue up 3x"),
# info = grey ("In Sifted this week"), risk = terracotta ("Competes with Cleo")

Health = Literal["good", "watch", "at_risk", "exited"]
# Portfolio board columns: at_risk = "Needs attention", watch = "Likely to raise soon",
# good = "Doing well", exited = "Exited"

DealStatus = Literal["new", "under_review", "passed"]

NodeKind = Literal["fund", "portfolio", "competitor", "pick", "theme"]  # theme: a sector hub (By theme view)
EdgeKind = Literal["owns", "competes", "similar", "candidate", "conflict"]
# owns: fund -> portfolio company (grey line)
# competes: portfolio company -> competitor (grey line)
# similar: pick -> the portfolio company it looks like (gold line)
# candidate: fund -> pick (faint gold line)
# conflict: pick -> portfolio company it clashes with (red line)

AgentName = Literal[
    "Partner", "Reader", "Thesis", "Market", "Mapper", "Deal Finder", "Analyst", "Critic", "Enricher"
]
EventType = Literal[
    "plan", "step", "tool", "handoff", "finding", "warning", "recovered", "done", "error", "answer"
]
AgentState = Literal["waiting", "working", "done", "error"]
StepState = Literal["waiting", "working", "done"]
RunStatus = Literal["running", "done", "error"]
Verdict = Literal["meeting", "pass", "dig_deeper"]


# ---------------------------------------------------------------------------
# Core objects
# ---------------------------------------------------------------------------


class Source(BaseModel):
    """Where a claim or signal comes from: a URL, a dataset row, or both."""

    label: str  # shown in the chip, e.g. "northbeam.health" or "dataset #4821"
    url: Optional[str] = None
    row_id: Optional[int] = None  # row in data/companies.csv


class Signal(BaseModel):
    kind: SignalKind
    label: str  # plain English, e.g. "Raising now"
    icon: str  # lucide icon name, e.g. "trending-up"
    source_url: Optional[str] = None


class Company(BaseModel):
    id: str  # slug, e.g. "northbeam-health"
    row_id: Optional[int] = None  # row in data/companies.csv (shown as "#4821")
    name: str
    one_liner: str
    sector: str
    stage: str  # "Pre-seed", "Seed", "Series A", ... or "Acquired" / "Public" for exits
    country: Optional[str] = None
    city: Optional[str] = None
    founded: Optional[int] = None
    website: Optional[str] = None
    logo: Optional[str] = None  # URL or "/logos/x.png"; null -> initial tile


class SectorShare(BaseModel):
    name: str
    count: int
    share: float  # 0..1
    color: str  # hex, for the segmented bar


class FundDNA(BaseModel):
    summary: str  # one plain sentence
    stage: str  # "Pre-seed & Seed"
    geo: str  # "UK & Europe"
    cheque: str  # "£0.5M – £2M"
    sectors: list[SectorShare] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class Fund(BaseModel):
    id: str  # slug, e.g. "localglobe"
    name: str
    url: str
    logo: Optional[str] = None
    dna: Optional[FundDNA] = None


class FundRef(BaseModel):
    id: str
    name: str


class WatchStatus(BaseModel):
    enabled: bool
    next_run_at: Optional[str] = None  # ISO 8601
    next_run_label: str  # "7:00 tomorrow"
    progress_done: int  # ring "4 of 7"
    progress_total: int


class FitPart(BaseModel):
    """One bar of the fit breakdown (from score_fit feature contributions)."""

    label: str  # "Like the portfolio", "Right stage", "Right location"
    value: float  # 0..1


class DealFlowItem(BaseModel):
    rank: int
    company: Company
    fit: int  # 0..100
    fit_parts: list[FitPart] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    why: list[str] = Field(default_factory=list)  # plain-English bullets
    seen_label: str  # "2h", "1d", "1w"
    status: DealStatus
    conflict_with: Optional[str] = None  # portfolio company id it clashes with
    memo_id: Optional[str] = None


class PortfolioItem(BaseModel):
    company: Company
    health: Health
    signals: list[Signal] = Field(default_factory=list)
    updated_label: Optional[str] = None  # "Updated 2d ago"; null for exits


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    company_id: Optional[str] = None
    logo: Optional[str] = None
    fit: Optional[int] = None  # picks only
    x: float  # top-left of a 160px-wide node box (fund node: 120px circle)
    y: float


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: EdgeKind
    label: Optional[str] = None  # plain English: "very similar", "same customers", "rival", "new bet"


class Claim(BaseModel):
    text: str
    source: Optional[Source] = None
    verified: bool


class MemoSection(BaseModel):
    title: str  # "Why it fits LocalGlobe", "Risks"
    claims: list[Claim]


class MemoTrust(BaseModel):
    """'Can you trust this memo?' block, written by the Critic."""

    claims_with_source: int
    claims_total: int
    checked_by_critic: bool
    not_verified: int
    conflicts: list[str] = Field(default_factory=list)  # empty -> "None"
    never_used: list[str] = Field(default_factory=list)
    disclaimer: str


class Memo(BaseModel):
    id: str
    company: Company
    title: str  # "Northbeam Health: first look"
    fit: int
    raising: Optional[str] = None  # "£1.5M"
    where: Optional[str] = None  # "Leeds, UK"
    sections: list[MemoSection]
    questions: list[str] = Field(default_factory=list)
    trust: MemoTrust
    decision: Optional[Verdict] = None
    created_at: str


class MemoSummary(BaseModel):
    id: str
    company: Company
    title: str
    fit: int
    created_at: str
    decision: Optional[Verdict] = None


class AgentEvent(BaseModel):
    seq: int  # 1, 2, 3 ... also the SSE "id:"
    ts: str  # ISO 8601
    elapsed_s: float  # seconds since run start, shown as "2:14"
    run_id: str
    agent: AgentName
    type: EventType
    message: str  # plain English, shown as-is
    tag: Optional[str] = None  # chip: "Plan", "Hand-off", "New match", "Recovered", ...
    data: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    label: str
    status: StepState


class AgentStatus(BaseModel):
    name: AgentName
    status: AgentState


class BacktestMethod(BaseModel):
    label: str  # "Bellwether model", "Keyword search", "Random pick"
    found: int
    total: int


class FeatureWeight(BaseModel):
    label: str
    share: float  # 0..1, all shares sum to 1
    color: str


class ModelCard(BaseModel):
    trained_on: str
    data: str
    method: str
    retrains: str
    never_used: list[str]


class Backtest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow the "model_card" field name

    fund_id: str
    enough_history: bool  # false -> show "Not enough history for this fund"
    held_out: int  # e.g. 20
    top_percent: int  # e.g. 5
    methods: list[BacktestMethod] = Field(default_factory=list)
    feature_weights: list[FeatureWeight] = Field(default_factory=list)
    model_card: ModelCard
    score_seconds: float  # time to score the whole dataset
    trained_at: str  # ISO 8601
    trained_label: str  # "2h ago"


# ---------------------------------------------------------------------------
# Response wrappers (one per endpoint)
# ---------------------------------------------------------------------------


class FundResponse(BaseModel):  # GET /api/fund
    fund: Fund
    covered_funds: list[FundRef]
    watch: WatchStatus
    new_deals: int  # sidebar badge on Deal Flow
    latest_run_id: Optional[str] = None


class DealCounts(BaseModel):
    all: int
    new: int
    under_review: int
    passed: int


class DealsResponse(BaseModel):  # GET /api/deals
    fund_id: str
    counts: DealCounts
    items: list[DealFlowItem]


class PortfolioKpis(BaseModel):
    companies_backed: int
    invested: str  # "£38M"
    likely_to_raise: int
    need_attention: int
    new_signals_this_week: int


class PortfolioColumn(BaseModel):
    health: Health
    title: str
    blurb: str
    count: int  # total in this column
    items: list[PortfolioItem]  # the ones shown
    more: int  # "+ N more"
    rest: list[PortfolioItem] = Field(default_factory=list)  # the hidden ones, shown when "+ N more" is clicked


class PortfolioResponse(BaseModel):  # GET /api/portfolio
    fund_id: str
    kpis: PortfolioKpis
    columns: list[PortfolioColumn]


class MapResponse(BaseModel):  # GET /api/map
    fund_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    shortlist: list[DealFlowItem]  # right panel "Next deals"
    picked_from: int  # "Picked from 10,000 startups"
    updated_label: str  # "updated 2 min ago"
    mix_label: str  # "Mix: 6 UK · 3 EU · 1 US · no founder traits used"
    view: str = "portfolio"  # portfolio | theme | new | competition | center
    center_id: Optional[str] = None  # set when the map is centred on one company
    note: Optional[str] = None  # one plain-English line saying what this view shows
    sectors: list[str] = Field(default_factory=list)  # filter options
    countries: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class MemosResponse(BaseModel):  # GET /api/memos
    items: list[MemoSummary]


class UniverseRow(BaseModel):
    company: Company
    fit: Optional[int] = None  # fit for the current fund, 0..100
    funding_usd: Optional[float] = None  # total raised (USD) from the CSV, when known


class UniverseResponse(BaseModel):  # GET /api/universe
    total: int  # rows matching the query
    dataset_size: int  # all rows in companies.csv
    sectors: int
    countries: int
    page: int
    page_size: int
    items: list[UniverseRow]
    options: Optional["UniverseOptions"] = None  # every filter value in the dataset (CSV only)


class UniverseOptions(BaseModel):
    sector: list[str] = []
    country: list[str] = []
    stage: list[str] = []
    founded: list[int] = []


class FundSummary(BaseModel):  # one row of GET /api/funds
    id: str
    name: str
    url: str
    logo: Optional[str] = None
    initials: str  # "LG"
    latest_run_id: Optional[str] = None
    last_run_at: Optional[str] = None  # ISO 8601
    has_results: bool  # pages have something to show


class FundsResponse(BaseModel):  # GET /api/funds
    items: list[FundSummary]


class RunCreate(BaseModel):  # POST /api/runs body
    fund_url: str
    task: Optional[str] = None


class RunCreated(BaseModel):  # POST /api/runs response
    run_id: str
    fund_id: str


class RunState(BaseModel):  # GET /api/runs/{id}
    run_id: str
    fund: Fund
    status: RunStatus
    task: str  # the user's request bubble
    started_at: str
    elapsed_s: float
    plan: list[PlanStep]
    agents: list[AgentStatus]
    partner_summary: Optional[str] = None
    since_last_run: Optional[str] = None  # "Since yesterday: 2 new matches, 1 competitor raised"
    shortlist: list[DealFlowItem] = Field(default_factory=list)
    memo_ids: list[str] = Field(default_factory=list)


class Feedback(BaseModel):  # POST /api/runs/{id}/feedback body
    company_id: str
    verdict: Verdict
    note: Optional[str] = None


class WatchRequest(BaseModel):  # POST /api/funds/{id}/watch body
    enabled: bool = True
    simulate_next_run: bool = False


class WatchResponse(BaseModel):
    watch: WatchStatus
    run_id: Optional[str] = None  # set when simulate_next_run started a run


class Ok(BaseModel):
    ok: bool = True


# ---------------------------------------------------------------------------
# Company detail page (GET /api/companies/{id}/detail)
# ---------------------------------------------------------------------------


class ScoreReason(BaseModel):
    label: str  # plain English, e.g. "Very like Goodlord", "Right stage (Pre-seed)"
    impact: float  # > 0 pushed the fit up, < 0 pulled it down (model units, for ordering and bar length)


class NearPortfolio(BaseModel):
    company_id: Optional[str] = None
    name: str
    score: Optional[float] = None  # 0..1 similarity


class CompanyScore(BaseModel):
    scored: bool  # false -> "Not scored for this fund yet"
    fit: Optional[int] = None  # 0..100, the number shown everywhere else
    model_fit: Optional[int] = None  # the model's fit before the judge blend
    judge: Optional[float] = None  # 0..1, "Fits the thesis (judge)" from Jev
    rank: Optional[int] = None  # place on the shortlist / scored list
    source_label: str  # "From the latest run", "Quick estimate from simple rules", ...
    parts: list[FitPart] = Field(default_factory=list)
    reasons: list[ScoreReason] = Field(default_factory=list)
    why: list[str] = Field(default_factory=list)
    feature_weights: list[FeatureWeight] = Field(default_factory=list)
    nearest_portfolio: list[NearPortfolio] = Field(default_factory=list)


class MarketInfo(BaseModel):
    description: Optional[str] = None  # "business banking"
    scope: Optional[str] = None  # "Global fintech market"
    size: Optional[str] = None  # "$882B"
    cagr: Optional[str] = None  # "17.0%"
    year: Optional[int] = None
    source: Optional[str] = None


class FundingInfo(BaseModel):
    """Display only. Investors and money raised are never used for scoring."""

    amount_label: Optional[str] = None  # "$1.2M"
    last_round_date: Optional[str] = None
    first_round_date: Optional[str] = None
    rounds: Optional[int] = None
    investors: list[str] = Field(default_factory=list)


class SimilarCompany(BaseModel):
    company: Company
    score: Optional[float] = None  # 0..1


class CompanyDetail(BaseModel):  # GET /api/companies/{id}/detail
    company: Company
    fund_id: str
    fund_name: str
    in_dataset: bool
    summary: Optional[str] = None
    problem: Optional[str] = None
    business_model: Optional[str] = None
    customers: Optional[str] = None
    stage_estimated: bool = False
    market: Optional[MarketInfo] = None
    funding: Optional[FundingInfo] = None
    score: CompanyScore
    signals: list[Signal] = Field(default_factory=list)
    deal_status: Optional[DealStatus] = None
    health: Optional[Health] = None  # set when the fund already owns it
    conflict_with: Optional[str] = None
    memo_id: Optional[str] = None
    similar: list[SimilarCompany] = Field(default_factory=list)
    similar_source: str = ""  # "Bellwether model" | "Word match (model offline)" | ""
    sources: list[Source] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str  # plain English


# ---------------------------------------------------------------------------
# Ask the team (POST /api/runs/{run_id}/ask, POST /api/funds/{fund_id}/ask)
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str


class AskCreated(BaseModel):  # POST .../ask response; the answer streams into the run feed
    question_id: str
    run_id: str


class AskSource(BaseModel):
    label: str
    url: Optional[str] = None
    company_id: Optional[str] = None


class QuestionItem(BaseModel):
    id: str
    run_id: str
    fund_id: str
    question: str
    status: Literal["working", "answered", "error"]
    personas: list[AgentName] = Field(default_factory=list)
    answer: Optional[str] = None  # markdown, cites sources as [1], [2]
    sources: list[AskSource] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    companies: list[Company] = Field(default_factory=list)  # the company_ids, for links
    unsure: bool = False
    asked_at: str
    answered_at: Optional[str] = None


class QuestionsResponse(BaseModel):  # GET /api/funds/{fund_id}/questions
    items: list[QuestionItem]  # oldest first
