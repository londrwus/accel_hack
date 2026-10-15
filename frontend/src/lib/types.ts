// Shared data shapes for Bellwether.
// Mirror of backend/app/models.py. Keep the two files IDENTICAL in shape.
// Field names are snake_case on both sides. See shared/contract.md.
// Optional[...] in Python = `T | null` here (the backend always sends the key).

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** timing = gold, strength = sage, info = grey, risk = terracotta */
export type SignalKind = "timing" | "strength" | "info" | "risk";

/** at_risk = "Needs attention", watch = "Likely to raise soon", good = "Doing well", exited = "Exited" */
export type Health = "good" | "watch" | "at_risk" | "exited";

export type DealStatus = "new" | "under_review" | "passed";

/** theme: a sector hub in the "By theme" view. A centred map draws its centre company as a "fund" bubble. */
export type NodeKind = "fund" | "portfolio" | "competitor" | "pick" | "theme";
/** owns: fund->portfolio · competes: portfolio->competitor · similar: pick->portfolio (gold)
 *  candidate: fund->pick (faint gold) · conflict: pick->portfolio (red) */
export type EdgeKind = "owns" | "competes" | "similar" | "candidate" | "conflict";

export type AgentName =
  | "Partner"
  | "Reader"
  | "Thesis"
  | "Market"
  | "Mapper"
  | "Deal Finder"
  | "Analyst"
  | "Critic"
  | "Enricher";
export type EventType =
  | "plan"
  | "step"
  | "tool"
  | "handoff"
  | "finding"
  | "warning"
  | "recovered"
  | "done"
  | "error"
  | "answer";
export type AgentState = "waiting" | "working" | "done" | "error";
export type StepState = "waiting" | "working" | "done";
export type RunStatus = "running" | "done" | "error";
export type Verdict = "meeting" | "pass" | "dig_deeper";

// ---------------------------------------------------------------------------
// Core objects
// ---------------------------------------------------------------------------

export interface Source {
  label: string; // "northbeam.health" or "dataset #4821"
  url: string | null;
  row_id: number | null; // row in data/companies.csv
}

export interface Signal {
  kind: SignalKind;
  label: string;
  icon: string; // lucide icon name, e.g. "trending-up"
  source_url: string | null;
}

export interface Company {
  id: string; // slug
  row_id: number | null; // shown as "#4821" (pad to 4 digits)
  name: string;
  one_liner: string;
  sector: string;
  stage: string; // "Seed", "Series A", ... or "Acquired" / "Public"
  country: string | null;
  city: string | null;
  founded: number | null;
  website: string | null;
  logo: string | null; // URL or "/logos/x.png"; null -> initial tile
}

export interface SectorShare {
  name: string;
  count: number;
  share: number; // 0..1
  color: string;
}

export interface FundDNA {
  summary: string;
  stage: string;
  geo: string;
  cheque: string;
  sectors: SectorShare[];
  themes: string[];
  sources: Source[];
}

export interface Fund {
  id: string;
  name: string;
  url: string;
  logo: string | null;
  dna: FundDNA | null;
}

export interface FundRef {
  id: string;
  name: string;
}

export interface WatchStatus {
  enabled: boolean;
  next_run_at: string | null;
  next_run_label: string;
  progress_done: number;
  progress_total: number;
}

export interface FitPart {
  label: string;
  value: number; // 0..1
}

export interface DealFlowItem {
  rank: number;
  company: Company;
  fit: number; // 0..100
  fit_parts: FitPart[];
  signals: Signal[];
  why: string[];
  seen_label: string;
  status: DealStatus;
  conflict_with: string | null;
  memo_id: string | null;
}

export interface PortfolioItem {
  company: Company;
  health: Health;
  signals: Signal[];
  updated_label: string | null;
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  company_id: string | null;
  logo: string | null;
  fit: number | null;
  x: number; // top-left of a 160px-wide node box (fund node: 120px circle)
  y: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  /** Plain English: "very similar", "same customers", "rival", "new bet". */
  label?: string | null;
}

export interface Claim {
  text: string;
  source: Source | null;
  verified: boolean;
}

export interface MemoSection {
  title: string;
  claims: Claim[];
}

export interface MemoTrust {
  claims_with_source: number;
  claims_total: number;
  checked_by_critic: boolean;
  not_verified: number;
  conflicts: string[];
  never_used: string[];
  disclaimer: string;
}

export interface Memo {
  id: string;
  company: Company;
  title: string;
  fit: number;
  raising: string | null;
  where: string | null;
  sections: MemoSection[];
  questions: string[];
  trust: MemoTrust;
  decision: Verdict | null;
  created_at: string;
}

export interface MemoSummary {
  id: string;
  company: Company;
  title: string;
  fit: number;
  created_at: string;
  decision: Verdict | null;
}

export interface AgentEvent {
  seq: number;
  ts: string;
  elapsed_s: number;
  run_id: string;
  agent: AgentName;
  type: EventType;
  message: string;
  tag: string | null;
  data: Record<string, unknown>;
}

export interface PlanStep {
  label: string;
  status: StepState;
}

export interface AgentStatus {
  name: AgentName;
  status: AgentState;
}

export interface BacktestMethod {
  label: string;
  found: number;
  total: number;
}

export interface FeatureWeight {
  label: string;
  share: number; // 0..1
  color: string;
}

export interface ModelCard {
  trained_on: string;
  data: string;
  method: string;
  retrains: string;
  never_used: string[];
}

export interface Backtest {
  fund_id: string;
  enough_history: boolean;
  held_out: number;
  top_percent: number;
  methods: BacktestMethod[];
  feature_weights: FeatureWeight[];
  model_card: ModelCard;
  score_seconds: number;
  trained_at: string;
  trained_label: string;
}

// ---------------------------------------------------------------------------
// Response wrappers (one per endpoint)
// ---------------------------------------------------------------------------

export interface FundResponse {
  fund: Fund;
  covered_funds: FundRef[];
  watch: WatchStatus;
  new_deals: number;
  latest_run_id: string | null;
}

export interface DealCounts {
  all: number;
  new: number;
  under_review: number;
  passed: number;
}

export interface DealsResponse {
  fund_id: string;
  counts: DealCounts;
  items: DealFlowItem[];
}

export interface PortfolioKpis {
  companies_backed: number;
  invested: string;
  likely_to_raise: number;
  need_attention: number;
  new_signals_this_week: number;
}

export interface PortfolioColumn {
  health: Health;
  title: string;
  blurb: string;
  count: number;
  items: PortfolioItem[];
  more: number;
  /** The hidden companies behind "+ N more" (older saved pages may not have them). */
  rest?: PortfolioItem[];
}

export interface PortfolioResponse {
  fund_id: string;
  kpis: PortfolioKpis;
  columns: PortfolioColumn[];
}

export interface MapResponse {
  fund_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  shortlist: DealFlowItem[];
  picked_from: number;
  updated_label: string;
  mix_label: string;
  /** portfolio | theme | new | competition | center */
  view?: MapView | "center";
  center_id?: string | null;
  /** One plain-English line saying what this view shows. */
  note?: string | null;
  sectors?: string[];
  countries?: string[];
  stages?: string[];
}
export type MapView = "portfolio" | "theme" | "new" | "competition";
export interface MapQuery {
  view?: MapView;
  center?: string;
  sector?: string;
  country?: string;
  stage?: string;
  limit?: number;
}

export interface MemosResponse {
  items: MemoSummary[];
}

export interface UniverseRow {
  company: Company;
  fit: number | null;
  /** Total raised in USD from the dataset, when known. */
  funding_usd?: number | null;
}

export interface UniverseOptions {
  sector: string[];
  country: string[];
  stage: string[];
  founded: number[];
}

/** One row of GET /api/funds (sidebar fund switcher). */
export interface FundSummary {
  id: string;
  name: string;
  url: string;
  logo: string | null;
  initials: string;
  latest_run_id: string | null;
  last_run_at: string | null;
  has_results: boolean;
}

export interface FundsResponse {
  items: FundSummary[];
}

export interface UniverseResponse {
  total: number;
  dataset_size: number;
  sectors: number;
  countries: number;
  page: number;
  page_size: number;
  items: UniverseRow[];
  /** Every filter value in the dataset (live backend only). */
  options?: UniverseOptions | null;
}

export interface RunCreate {
  fund_url: string;
  task: string | null;
  /** true = always start a fresh run; otherwise the backend reuses the fund's latest finished run. */
  force?: boolean;
}

export interface RunCreated {
  run_id: string;
  fund_id: string;
  /** true when the backend returned an earlier finished run instead of starting one. */
  reused?: boolean;
}

export interface RunState {
  run_id: string;
  fund: Fund;
  status: RunStatus;
  task: string;
  started_at: string;
  elapsed_s: number;
  plan: PlanStep[];
  agents: AgentStatus[];
  partner_summary: string | null;
  since_last_run: string | null;
  shortlist: DealFlowItem[];
  memo_ids: string[];
}

export interface Feedback {
  company_id: string;
  verdict: Verdict;
  note: string | null;
}

export interface WatchRequest {
  enabled: boolean;
  simulate_next_run: boolean;
}

export interface WatchResponse {
  watch: WatchStatus;
  run_id: string | null;
}

export interface Ok {
  ok: boolean;
}

// ---------------------------------------------------------------------------
// Company detail page (GET /api/companies/{id}/detail)
// ---------------------------------------------------------------------------

export interface ScoreReason {
  label: string; // "Very like Goodlord", "Right stage (Pre-seed)"
  impact: number; // > 0 pushed the fit up, < 0 pulled it down
}

export interface NearPortfolio {
  company_id: string | null;
  name: string;
  score: number | null; // 0..1
}

export interface CompanyScore {
  scored: boolean; // false -> "Not scored for this fund yet"
  fit: number | null;
  model_fit: number | null;
  judge: number | null; // 0..1, "Fits the thesis (judge)"
  rank: number | null;
  source_label: string;
  parts: FitPart[];
  reasons: ScoreReason[];
  why: string[];
  feature_weights: FeatureWeight[];
  nearest_portfolio: NearPortfolio[];
}

export interface MarketInfo {
  description: string | null;
  scope: string | null;
  size: string | null;
  cagr: string | null;
  year: number | null;
  source: string | null;
}

/** Display only. Investors and money raised are never used for scoring. */
export interface FundingInfo {
  amount_label: string | null;
  last_round_date: string | null;
  first_round_date: string | null;
  rounds: number | null;
  investors: string[];
}

export interface SimilarCompany {
  company: Company;
  score: number | null;
}

export interface CompanyDetail {
  company: Company;
  fund_id: string;
  fund_name: string;
  in_dataset: boolean;
  summary: string | null;
  problem: string | null;
  business_model: string | null;
  customers: string | null;
  stage_estimated: boolean;
  market: MarketInfo | null;
  funding: FundingInfo | null;
  score: CompanyScore;
  signals: Signal[];
  deal_status: DealStatus | null;
  health: Health | null;
  conflict_with: string | null;
  memo_id: string | null;
  similar: SimilarCompany[];
  similar_source: string;
  sources: Source[];
}

export interface ErrorResponse {
  error: string;
}

// ---------------------------------------------------------------------------
// Ask the team (chat on /research)
// ---------------------------------------------------------------------------

export interface AskRequest {
  question: string;
}

/** POST /api/runs/{run_id}/ask and POST /api/funds/{fund_id}/ask (202). The answer streams into the run feed. */
export interface AskCreated {
  question_id: string;
  run_id: string;
}

export interface AskSource {
  label: string;
  url: string | null;
  company_id: string | null;
}

export interface QuestionItem {
  id: string;
  run_id: string;
  fund_id: string;
  question: string;
  status: "working" | "answered" | "error";
  personas: AgentName[];
  /** Markdown; cites sources as [1], [2]. */
  answer: string | null;
  sources: AskSource[];
  company_ids: string[];
  companies: Company[];
  unsure: boolean;
  asked_at: string;
  answered_at: string | null;
}

/** GET /api/funds/{fund_id}/questions, oldest first. */
export interface QuestionsResponse {
  items: QuestionItem[];
}
