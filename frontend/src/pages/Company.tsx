import { SkeletonRows } from "@/components/Skeleton";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion, MotionConfig } from "motion/react";
import { ArrowLeft, ArrowRight, Check, ExternalLink, Globe, Minus, Plus } from "lucide-react";
import { Button } from "@/components/Button";
import { Badge, DealStatusBadge } from "@/components/Badge";
import { Chip, SourceChip } from "@/components/Chip";
import { CompanyLogo } from "@/components/CompanyLogo";
import { SignalChip } from "@/components/SignalChip";
import { BarLegend, SegmentedBar } from "@/components/DataCard";
import { ApiError, getCompanyDetail, getCompanySimilar } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useActiveFundId } from "@/lib/fund";
import { cn } from "@/lib/utils";
import { formatRowId, isStrongFit, stageView } from "@/lib/format";
import type { CompanyDetail, CompanyScore, Health } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;

const HEALTH_LABEL: Record<Health, { label: string; tone: "danger" | "gold" | "sage" | "grey" }> = {
  at_risk: { label: "Needs attention", tone: "danger" },
  watch: { label: "Likely to raise soon", tone: "gold" },
  good: { label: "Doing well", tone: "sage" },
  exited: { label: "Exited", tone: "grey" },
  unknown: { label: "Unknown", tone: "grey" },
};

/** Hairline card with a quiet title, like the rest of the platform. */
function Section({ title, aside, children, className }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("flex w-full shrink-0 flex-col overflow-hidden rounded-[14px] hairline bg-panel", className)}>
      <div className="flex items-center justify-between border-b border-hair p-[11px_16px]">
        <h2 className="m-0 text-[13px] font-normal tracking-[0.1px] text-muted">{title}</h2>
        {aside && <span className="text-[12px] tracking-[0.1px] text-subtle">{aside}</span>}
      </div>
      <div className="flex flex-col gap-[12px] p-[14px_16px_16px]">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-[3px]">
      <span className="text-[12px] tracking-[0.3px] text-subtle">{label}</span>
      <span className="text-[14px] leading-[21px] text-ink">{children}</span>
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="m-0 text-[13px] leading-[19px] text-subtle">{children}</p>;
}

function PartBar({ label, value, strong, delay }: { label: string; value: number; strong: boolean; delay: number }) {
  const pct = Math.round(value * 100);
  const judge = label.toLowerCase().includes("judge");
  return (
    <div className="flex items-center gap-[12px]">
      <span className="w-[170px] shrink-0 truncate text-[13px] text-muted" title={label}>
        {label}
      </span>
      <span className="flex h-[6px] min-w-0 flex-1 rounded-[3px] bg-[#1A18170F]" aria-hidden>
        <motion.span
          className={cn("h-[6px] rounded-[3px]", judge ? "bg-accent" : strong ? "bg-predicted" : "bg-competitor")}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, delay, ease: EASE }}
        />
      </span>
      <span className="w-[38px] text-right font-mono text-[12px] text-subtle">{pct}%</span>
    </div>
  );
}

function ScoreCard({ score, fundName, fundId }: { score: CompanyScore; fundName: string; fundId: string }) {
  if (!score.scored || score.fit == null) {
    return (
      <Section title={`How it scored for ${fundName}`}>
        <Empty>Not scored for this fund yet. Start a run for {fundName} and Bellwether will score every startup in the dataset.</Empty>
      </Section>
    );
  }
  const strong = isStrongFit(score.fit);
  const ups = score.reasons.filter((r) => r.impact >= 0).slice(0, 5);
  const downs = score.reasons.filter((r) => r.impact < 0).slice(0, 3);
  const weights = score.feature_weights.map((w) => ({ label: w.label, share: w.share, color: w.color }));
  return (
    <Section title={`How it scored for ${fundName}`} aside={score.source_label}>
      <div className="flex items-end gap-[16px]">
        <div className="flex items-baseline gap-[4px]">
          <span className={cn("text-[48px] font-normal leading-[52px] tracking-[-1px]", strong ? "text-predicted" : "text-ink")}>
            {score.fit}
          </span>
          <span className="text-[18px] text-subtle">% fit</span>
        </div>
        <div className="flex flex-col gap-[2px] pb-[8px] text-[12px] tracking-[0.1px] text-subtle">
          {score.rank != null && <span>Ranked #{score.rank} for {fundName}</span>}
          {score.model_fit != null && score.judge != null && (
            <span>
              Model {score.model_fit}% · judge {Math.round(score.judge * 100)}%
            </span>
          )}
        </div>
      </div>
      <p className="m-0 text-[12px] leading-[17px] text-subtle">
        Fit means "looks like what {fundName} has backed before", not "will succeed". A partner always makes the call.
      </p>

      {score.parts.length > 0 && (
        <div className="flex flex-col gap-[9px] pt-[4px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">What the score is made of</span>
          {score.parts.map((p, i) => (
            <PartBar key={p.label} label={p.label} value={p.value} strong={strong} delay={0.1 + i * 0.05} />
          ))}
        </div>
      )}

      {(ups.length > 0 || downs.length > 0) && (
        <div className="flex flex-col gap-[6px] pt-[4px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">What moved the score</span>
          {ups.map((r) => (
            <div key={r.label} className="flex items-center gap-[8px] text-[13px] text-ink">
              <span className="flex size-[16px] shrink-0 items-center justify-center rounded-full bg-accent-soft">
                <Plus size={10} className="text-accent" aria-hidden />
              </span>
              {r.label}
            </div>
          ))}
          {downs.map((r) => (
            <div key={r.label} className="flex items-center gap-[8px] text-[13px] text-ink">
              <span className="flex size-[16px] shrink-0 items-center justify-center rounded-full bg-warning-soft">
                <Minus size={10} className="text-danger" aria-hidden />
              </span>
              {r.label}
            </div>
          ))}
        </div>
      )}

      {score.why.length > 0 && (
        <div className="flex flex-col gap-[6px] pt-[4px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">Why it fits {fundName}</span>
          {score.why.map((w) => (
            <div key={w} className="flex items-start gap-[8px] text-[13px] leading-[19px] text-ink">
              <span className="mt-[2px] flex size-[16px] shrink-0 items-center justify-center rounded-full bg-accent-soft">
                <Check size={10} className="text-accent" aria-hidden />
              </span>
              {w}
            </div>
          ))}
        </div>
      )}

      {score.nearest_portfolio.length > 0 && (
        <div className="flex flex-col gap-[6px] pt-[4px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">Closest companies {fundName} already owns</span>
          <div className="flex flex-wrap gap-[6px]">
            {score.nearest_portfolio.map((n) => {
              const label = `${n.name}${n.score != null ? ` · ${Math.round(n.score * 100)}% alike` : ""}`;
              return n.company_id ? (
                <Link key={n.name} to={`/companies/${encodeURIComponent(n.company_id)}?fund=${fundId}`} className="hover:opacity-80">
                  <Badge tone="sage">{label}</Badge>
                </Link>
              ) : (
                <Badge key={n.name} tone="sage">
                  {label}
                </Badge>
              );
            })}
          </div>
        </div>
      )}

      {weights.length > 0 && (
        <div className="flex flex-col gap-[8px] pt-[6px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">What the model weighs most for {fundName}</span>
          <SegmentedBar segments={weights} />
          <BarLegend segments={weights} showPercent={false} />
        </div>
      )}
    </Section>
  );
}

function Header({ d, fundId }: { d: CompanyDetail; fundId: string }) {
  const c = d.company;
  const stage = stageView({ stage: c.stage, stage_estimated: d.stage_estimated });
  const site = c.website ? (c.website.includes("://") ? c.website : `https://${c.website}`) : null;
  const navigate = useNavigate();
  return (
    <header className="flex shrink-0 items-center justify-between gap-[16px] border-b border-hair p-[18px_24px]">
      <div className="flex min-w-0 items-center gap-[14px]">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Back"
          className="flex size-[30px] shrink-0 items-center justify-center rounded-full text-muted hairline hover:text-ink"
        >
          <ArrowLeft size={15} />
        </button>
        <CompanyLogo name={c.name} logo={c.logo} size={48} radius={12} tone={d.health ? "sage" : "grey"} />
        <div className="flex min-w-0 flex-col gap-[5px]">
          <div className="flex items-center gap-[10px]">
            <h1 className="m-0 truncate text-[22px] font-normal tracking-[-0.3px] text-ink">{c.name}</h1>
            {d.deal_status && <DealStatusBadge status={d.deal_status} />}
            {d.health && <Badge tone={HEALTH_LABEL[d.health].tone}>{`In the portfolio · ${HEALTH_LABEL[d.health].label}`}</Badge>}
          </div>
          {c.one_liner && <p className="m-0 truncate text-[14px] text-muted">{c.one_liner}</p>}
          <div className="flex flex-wrap items-center gap-[6px]">
            <Chip size="sm">{c.sector}</Chip>
            {stage.label !== "–" && (
              <Chip size="sm" title={stage.estimated ? "Worked out from the latest funding round" : undefined}>
                {stage.label}
                {stage.estimated && <span className="text-subtle"> · estimated</span>}
              </Chip>
            )}
            {(c.city || c.country) && <Chip size="sm">{[c.city, c.country].filter(Boolean).join(", ")}</Chip>}
            {c.founded != null && <Chip size="sm">Founded {c.founded}</Chip>}
            {c.row_id != null && (
              <Chip size="sm" mono>
                dataset {formatRowId(c.row_id)}
              </Chip>
            )}
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-[8px]">
        {site && (
          <a
            href={site}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-[6px] whitespace-nowrap rounded-[12px] bg-panel p-[9px_16px] text-[14px] font-medium tracking-[0.1px] text-ink shadow-btn hairline hover:opacity-90"
          >
            <Globe size={15} aria-hidden />
            {c.website?.replace(/^https?:\/\//, "")}
            <ExternalLink size={13} className="text-subtle" aria-hidden />
          </a>
        )}
        {d.memo_id && (
          <Button variant="gold" iconRight={ArrowRight} to={`/memos/${encodeURIComponent(d.memo_id)}?fund=${fundId}`}>
            Read memo
          </Button>
        )}
      </div>
    </header>
  );
}

function Body({ d, fundId }: { d: CompanyDetail; fundId: string }) {
  const c = d.company;
  const about: [string, string | null][] = [
    ["What they do", d.summary || c.one_liner || null],
    ["The problem", d.problem],
    ["How they make money", d.business_model],
    ["Customers", d.customers],
  ];
  const aboutRows = about.filter(([, v]) => v);
  return (
    <div className="flex min-h-0 flex-1 items-start gap-[16px] overflow-auto bg-[#1A181703] p-[20px_24px_24px]">
      <div className="flex min-w-0 flex-[1.15] flex-col gap-[16px]">
        <Section title="About">
          {aboutRows.length ? (
            aboutRows.map(([label, v]) => (
              <Field key={label} label={label}>
                {v}
              </Field>
            ))
          ) : (
            <Empty>We only know the name so far. It isn't in the startup dataset yet.</Empty>
          )}
        </Section>

        <Section title="Signals" aside={d.signals.length ? "Click the arrow to open the source" : undefined}>
          {d.signals.length ? (
            <div className="flex flex-col gap-[10px]">
              {d.signals.map((s) => (
                <div key={s.label} className="flex items-center justify-between gap-[10px]">
                  <SignalChip signal={{ ...s, source_url: null }} />
                  {s.source_url ? (
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-w-0 items-center gap-[4px] truncate text-[12px] text-subtle hover:text-muted"
                    >
                      <span className="truncate">{s.source_url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}</span>
                      <ExternalLink size={11} aria-hidden />
                    </a>
                  ) : (
                    <span className="text-[12px] text-subtle">From the dataset and the run</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty>No signals for this company yet.</Empty>
          )}
        </Section>

        <Section title="Market">
          {d.market ? (
            <div className="grid grid-cols-2 gap-[14px]">
              {d.market.description && <Field label="Market">{d.market.description}</Field>}
              {d.market.scope && <Field label="Wider market">{d.market.scope}</Field>}
              {d.market.size && (
                <Field label="Market size">
                  {d.market.size}
                  {d.market.year ? <span className="text-subtle"> by {d.market.year}</span> : null}
                </Field>
              )}
              {d.market.cagr && <Field label="Growth per year">{d.market.cagr}</Field>}
              {d.market.source && <Field label="Source">{d.market.source}</Field>}
            </div>
          ) : (
            <Empty>No market figures for this company yet.</Empty>
          )}
        </Section>

        <Section title="Funding & investors" aside="Shown for context. Never used to score.">
          {d.funding ? (
            <>
              <div className="grid grid-cols-3 gap-[14px]">
                <Field label="Latest round">{d.funding.amount_label ?? "Not disclosed"}</Field>
                <Field label="Round date">{d.funding.last_round_date ?? "–"}</Field>
                <Field label="Rounds">{d.funding.rounds ?? "–"}</Field>
              </div>
              {d.funding.investors.length > 0 && (
                <div className="flex flex-col gap-[6px]">
                  <span className="text-[12px] tracking-[0.3px] text-subtle">Investors</span>
                  <div className="flex flex-wrap gap-[6px]">
                    {d.funding.investors.map((i) => (
                      <Chip key={i} size="md">
                        {i}
                      </Chip>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <Empty>No funding rounds on record.</Empty>
          )}
        </Section>
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-[16px]">
        <ScoreCard score={d.score} fundName={d.fund_name} fundId={fundId} />

        <SimilarSection d={d} fundId={fundId} />

        <Section title="Data sources">
          {d.sources.length ? (
            <div className="flex flex-wrap gap-[6px]">
              {d.sources.map((s) => (
                <SourceChip key={s.label} source={s} />
              ))}
            </div>
          ) : (
            <Empty>Read from {d.fund_name}'s website during the run.</Empty>
          )}
          <p className="m-0 text-[12px] leading-[17px] text-subtle">
            Founder gender, age, ethnicity and nationality are never used. Bellwether never contacts founders.
          </p>
        </Section>
      </div>
    </div>
  );
}

/** "Companies like this": loaded after the page shows (the model call can take a few seconds). */
function SimilarSection({ d, fundId }: { d: CompanyDetail; fundId: string }) {
  const { data, loading } = useApi(
    () => (d.similar.length ? Promise.resolve({ similar: d.similar, similar_source: d.similar_source }) : getCompanySimilar(d.company.id, fundId)),
    [d.company.id, fundId],
  );
  const similar = data?.similar ?? [];
  return (
    <Section title="Companies like this" aside={data?.similar_source || undefined}>
      {loading ? (
        <SkeletonRows rows={4} label="Finding companies like this" />
      ) : similar.length ? (
        <div className="flex flex-col">
          {similar.map((s) => (
            <Link
              key={s.company.id}
              to={`/companies/${encodeURIComponent(s.company.id)}?fund=${fundId}`}
              className="-mx-[8px] flex items-center gap-[10px] rounded-[10px] p-[8px] transition-colors hover:bg-[#1A181708]"
            >
              <CompanyLogo name={s.company.name} logo={s.company.logo} size={28} radius={7} />
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[13px] font-medium text-ink">{s.company.name}</span>
                <span className="truncate text-[12px] text-subtle">{s.company.one_liner}</span>
              </div>
              <span className="shrink-0 text-[12px] text-subtle">{s.company.sector}</span>
            </Link>
          ))}
        </div>
      ) : (
        <Empty>We couldn't find similar companies right now.</Empty>
      )}
    </Section>
  );
}

/** /companies/:id: everything about one company and how it scored for the current fund. */
export default function Company() {
  const { id = "" } = useParams();
  const fundId = useActiveFundId();
  const { data, error, loading } = useApi(() => getCompanyDetail(id, fundId), [id, fundId]);
  const notFound = error instanceof ApiError && error.status === 404;

  return (
    <MotionConfig reducedMotion="user">
      {data ? (
        <>
          <Header d={data} fundId={fundId} />
          <Body d={data} fundId={fundId} />
        </>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-[12px] p-[24px] text-[14px] text-muted">
          {loading
            ? <SkeletonRows rows={7} label="Loading the company" />
            : notFound
              ? "We couldn't find that company."
              : `Couldn't load the company. ${error?.message ?? ""}`}
          {!loading && (
            <div>
              <Button variant="white" size="sm" to="/deals">
                Back to Deal Flow
              </Button>
            </div>
          )}
        </div>
      )}
    </MotionConfig>
  );
}
