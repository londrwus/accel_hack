import { Fragment, useMemo, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import {
  Banknote,
  CalendarDays,
  CircleAlert,
  CircleCheck,
  CircleQuestionMark,
  MapPin,
  Sprout,
  Tag,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Chip, SourceChip } from "@/components/Chip";
import { Segmented } from "@/components/Segmented";
import { formatRowId, isStrongFit } from "@/lib/format";
import { SOURCE_KINDS, SOURCE_KIND_ORDER, sourceKind, type SourceKind } from "@/lib/sourceKind";
import type { Claim, Memo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { isSourced } from "./trust";

export const EASE = [0.22, 1, 0.36, 1] as const;

/** Seconds between memo blocks fading in ("sections fade in as the Analyst finishes them"). */
const SECTION_STEP = 0.12;
/** Seconds between Critic source badges popping in, after the text is in. */
const BADGE_STEP = 0.07;

function Reveal({ index, children, className }: { index: number; children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE, delay: 0.05 + index * SECTION_STEP }}
    >
      {children}
    </motion.div>
  );
}

function SectionLabel({ children, count }: { children: ReactNode; count?: number }) {
  return (
    <div className="flex items-center gap-[8px] whitespace-nowrap text-[12px] uppercase tracking-[1px] text-subtle">
      {children}
      {count != null && <span className="tracking-[0.2px] normal-case">{count}</span>}
    </div>
  );
}

/** Numbers, money and percentages stand out so the memo can be skimmed. */
const NUMBER = /([£$€]?\d[\d,.]*\s?(?:%|bn\b|m\b|k\b|M\b|K\b|x\b)?)/g;
function Emph({ text }: { text: string }) {
  const parts = text.split(NUMBER);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className="font-medium">
            {p}
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

/** The source chip for one claim. Dataset rows say which row of data/companies.csv backs the claim. */
function ClaimSource({ claim, delay }: { claim: Claim; delay: number }) {
  const sourced = isSourced(claim);
  const rowId = claim.source?.row_id ?? null;
  const tip = !sourced
    ? "The Critic could not find a source for this claim"
    : claim.source?.url
      ? claim.source.url
      : rowId != null
        ? `Row ${formatRowId(rowId)} in data/companies.csv`
        : `Source: ${claim.source?.label}`;
  return (
    <motion.span
      className="flex shrink-0"
      title={tip}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ scale: { type: "spring", stiffness: 520, damping: 22, delay }, opacity: { duration: 0.2, delay } }}
    >
      <SourceChip source={claim.source} verified={sourced} />
    </motion.span>
  );
}

/** One line of the memo: status icon, the claim, its source chip. */
function Row({
  icon: Icon,
  iconClass,
  iconTitle,
  text,
  tone = "ink",
  tag,
  right,
}: {
  icon: LucideIcon;
  iconClass: string;
  iconTitle?: string;
  text: string;
  tone?: "ink" | "warning";
  tag?: string | null;
  right?: ReactNode;
}) {
  return (
    <div className="flex w-full items-start gap-[10px] py-[7px]">
      <span className="flex h-[21px] shrink-0 items-center" title={iconTitle}>
        <Icon size={15} strokeWidth={1.75} className={iconClass} aria-label={iconTitle} />
      </span>
      <p className={cn("m-0 min-w-0 flex-1 text-[14px]/[21px] tracking-[0.2px]", tone === "warning" ? "text-warning" : "text-ink")}>
        <Emph text={text} />
        {tag && <span className="ml-[8px] whitespace-nowrap text-[11px] tracking-[0.3px] text-subtle">{tag}</span>}
      </p>
      {right}
    </div>
  );
}

function ClaimRow({ claim, delay, tag }: { claim: Claim; delay: number; tag?: string | null }) {
  const ok = isSourced(claim);
  return (
    <Row
      icon={ok ? CircleCheck : TriangleAlert}
      iconClass={ok ? "text-accent" : "text-warning"}
      iconTitle={ok ? "Checked by the Critic" : "Not verified"}
      text={claim.text}
      tone={ok ? "ink" : "warning"}
      tag={tag}
      right={<ClaimSource claim={claim} delay={delay} />}
    />
  );
}

/** Icon + label + value, e.g. [pin] Where  Leeds, UK. */
function Fact({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-[6px]">
      <Icon size={14} strokeWidth={1.75} className="text-subtle" aria-hidden />
      <span className="text-[13px] tracking-[0.2px] text-subtle">{label}</span>
      <Chip size="md">{children}</Chip>
    </span>
  );
}

function Stat({ value, label, tone = "ink" }: { value: ReactNode; label: string; tone?: "ink" | "accent" | "warning" }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-[2px] px-[16px] first:pl-0 [&+&]:border-l [&+&]:border-hair">
      <span
        className={cn(
          "text-[22px]/[28px] tracking-[-0.2px] tabular-nums",
          tone === "accent" ? "text-accent" : tone === "warning" ? "text-warning" : "text-ink",
        )}
      >
        {value}
      </span>
      <span className="whitespace-nowrap text-[12px] tracking-[0.2px] text-subtle">{label}</span>
    </div>
  );
}

type GroupKey = SourceKind | "unsourced";
interface Item {
  claim: Claim;
  section: string;
  delay: number;
}

const isRiskSection = (title: string) => /risk|concern|red flag/i.test(title);

/** The one-page memo column (760px, centred): title + fit, key facts, evidence grouped by source, risks, founder questions. */
export function MemoDoc({ memo }: { memo: Memo }) {
  const where = memo.where ?? ([memo.company.city, memo.company.country].filter(Boolean).join(", ") || null);
  const strong = isStrongFit(memo.fit);
  const [filter, setFilter] = useState<"all" | GroupKey>("all");

  const { groups, risks, stats, multiSection } = useMemo(() => {
    const factSections = memo.sections.filter((s) => !isRiskSection(s.title));
    const riskClaims = memo.sections.filter((s) => isRiskSection(s.title)).flatMap((s) => s.claims);
    const all = memo.sections.flatMap((s) => s.claims);
    // Badges pop in one by one once the text is in.
    const badgesStart = 0.05 + 6 * SECTION_STEP;
    let b = 0;
    const byKind = new Map<GroupKey, Item[]>();
    for (const s of factSections) {
      for (const claim of s.claims) {
        const k: GroupKey = isSourced(claim) || claim.source ? (sourceKind(claim.source, memo.company.website) ?? "unsourced") : "unsourced";
        const list = byKind.get(k) ?? [];
        list.push({ claim, section: s.title, delay: 0 });
        byKind.set(k, list);
      }
    }
    const order: GroupKey[] = [...SOURCE_KIND_ORDER, "unsourced"];
    const groups = order
      .filter((k) => byKind.has(k))
      .map((k) => ({ key: k, items: byKind.get(k)!.map((it) => ({ ...it, delay: badgesStart + b++ * BADGE_STEP })) }));
    const risks = riskClaims.map((claim) => ({ claim, delay: badgesStart + b++ * BADGE_STEP }));
    const kinds = new Set(all.filter((c) => c.source).map((c) => sourceKind(c.source, memo.company.website)));
    return {
      groups,
      risks,
      multiSection: factSections.length > 1,
      stats: {
        total: all.length,
        verified: all.filter(isSourced).length,
        kinds: kinds.size,
        risks: riskClaims.length,
      },
    };
  }, [memo]);

  const activeFilter = filter !== "all" && !groups.some((g) => g.key === filter) ? "all" : filter;
  const groupMeta = (k: GroupKey) =>
    k === "unsourced" ? { label: "No source yet", short: "Unsourced", icon: CircleAlert } : SOURCE_KINDS[k];

  return (
    <article className="flex w-[760px] max-w-full shrink-0 flex-col gap-[22px] py-[32px]">
      <Reveal index={0} className="flex w-full flex-col gap-[14px]">
        <div className="flex w-full items-center justify-between gap-[16px]">
          <h2 className="m-0 min-w-0 truncate text-[28px] font-normal tracking-[-0.3px] text-ink">
            <Link
              to={`/companies/${encodeURIComponent(memo.company.id)}`}
              title={`Open ${memo.company.name}'s company page`}
              className="text-ink decoration-hair underline-offset-4 hover:underline print:no-underline"
            >
              {memo.title}
            </Link>
          </h2>
          <span
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full p-[5px_12px] text-[13px] tracking-[0.2px]",
              strong ? "bg-predicted-soft text-predicted" : "bg-chip text-muted",
            )}
          >
            {memo.fit}% fit
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-[18px] gap-y-[8px]">
          {memo.company.stage && (
            <Fact icon={Sprout} label="Stage">
              {memo.company.stage}
            </Fact>
          )}
          {where && (
            <Fact icon={MapPin} label="Where">
              {where}
            </Fact>
          )}
          {memo.raising && (
            <Fact icon={Banknote} label="Raising">
              {memo.raising}
            </Fact>
          )}
          {memo.company.sector && (
            <Fact icon={Tag} label="Sector">
              {memo.company.sector}
            </Fact>
          )}
          {memo.company.founded && (
            <Fact icon={CalendarDays} label="Founded">
              {memo.company.founded}
            </Fact>
          )}
        </div>
      </Reveal>

      {stats.total > 0 && (
        <Reveal index={1} className="flex w-full border-y border-hair py-[12px]">
          <Stat value={stats.total} label="claims" />
          <Stat value={stats.verified} label="checked by the Critic" tone="accent" />
          <Stat value={stats.total - stats.verified} label="not verified" tone={stats.total - stats.verified > 0 ? "warning" : "ink"} />
          <Stat value={stats.kinds} label="kinds of source" />
          <Stat value={stats.risks} label="risks" />
        </Reveal>
      )}

      {groups.length > 0 && (
        <Reveal index={2} className="flex w-full flex-col gap-[12px]">
          <div className="flex w-full flex-wrap items-center justify-between gap-[10px]">
            <SectionLabel>Evidence by source</SectionLabel>
            {groups.length > 1 && (
              <Segmented
                aria-label="Filter evidence by source"
                className="print:hidden"
                value={activeFilter}
                onChange={setFilter}
                options={[
                  { value: "all", label: "All", count: groups.reduce((n, g) => n + g.items.length, 0) },
                  ...groups.map((g) => ({ value: g.key, label: groupMeta(g.key).short, count: g.items.length })),
                ]}
              />
            )}
          </div>
          <div className="flex w-full flex-col gap-[14px]">
            {groups.map((g) => {
              const meta = groupMeta(g.key);
              const Icon = meta.icon;
              const shown = activeFilter === "all" || activeFilter === g.key;
              return (
                <section key={g.key} className={cn("flex w-full flex-col", shown ? "flex" : "hidden print:flex")}>
                  <div className="flex items-center gap-[8px] border-b border-hair pb-[7px]">
                    <span
                      className={cn(
                        "flex size-[24px] items-center justify-center rounded-[7px]",
                        g.key === "unsourced" ? "bg-warning-soft text-warning" : "bg-chip text-muted",
                      )}
                    >
                      <Icon size={13} strokeWidth={1.75} aria-hidden />
                    </span>
                    <span className="text-[14px] tracking-[0.2px] text-ink">{meta.label}</span>
                    <span className="text-[12px] tracking-[0.2px] text-subtle">{g.items.length}</span>
                  </div>
                  <div className="flex flex-col pt-[3px]">
                    {g.items.map((it, j) => (
                      <ClaimRow key={j} claim={it.claim} delay={it.delay} tag={multiSection ? it.section : null} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </Reveal>
      )}

      {risks.length > 0 && (
        <Reveal index={3} className="flex w-full flex-col gap-[6px]">
          <SectionLabel count={risks.length}>Risks</SectionLabel>
          <div className="flex flex-col">
            {risks.map((r, i) => (
              <Row
                key={i}
                icon={TriangleAlert}
                iconClass="text-warning"
                iconTitle="Risk"
                text={r.claim.text}
                right={<ClaimSource claim={r.claim} delay={r.delay} />}
              />
            ))}
          </div>
        </Reveal>
      )}

      {memo.questions.length > 0 && (
        <Reveal index={4} className="flex w-full flex-col gap-[6px]">
          <SectionLabel count={memo.questions.length}>Questions for the founder</SectionLabel>
          <div className="flex flex-col">
            {memo.questions.map((q, i) => (
              <Row key={i} icon={CircleQuestionMark} iconClass="text-subtle" iconTitle="Open question" text={q} />
            ))}
          </div>
        </Reveal>
      )}

      {memo.sections.length === 0 && (
        <Chip size="sm" className="self-start">
          The Analyst has not written any sections yet
        </Chip>
      )}
    </article>
  );
}
