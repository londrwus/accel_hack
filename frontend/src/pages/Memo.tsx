import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { MotionConfig } from "motion/react";
import { Check, ChevronRight, Download, Share } from "lucide-react";
import { Button } from "@/components/Button";
import { ApiError, getMemo, getMemos } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { DEMO_FUND_ID, useActiveFundId, useActiveFundSummary } from "@/lib/fund";
import { FundEmptyState } from "@/components/FundEmptyState";
import type { Memo as MemoT, MemoSummary } from "@/lib/types";
import { MemoDoc } from "./Memo/MemoDoc";
import { DecisionRail } from "./Memo/DecisionRail";
import { computeTrust } from "./Memo/trust";

interface Loaded {
  memo: MemoT | null;
  list: MemoSummary[] | null;
}

/** /memos/:id shows that memo. /memos (no id) shows the newest memo. */
async function loadMemo(id: string | undefined, fundId: string): Promise<Loaded> {
  if (id) {
    try {
      return { memo: await getMemo(id, fundId), list: null };
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        const list = await getMemos(fundId).then((r) => r.items, () => []);
        return { memo: null, list };
      }
      throw e;
    }
  }
  const list = (await getMemos(fundId)).items;
  return { memo: list.length ? await getMemo(list[0].id, fundId) : null, list };
}

function Header({ crumb, actions }: { crumb: ReactNode; actions?: ReactNode }) {
  return (
    <header className="box-border flex h-[84px] shrink-0 items-center justify-between border-b border-hair px-[24px] print:hidden">
      <div className="flex min-w-0 flex-col gap-[2px]">
        <nav aria-label="Breadcrumb" className="flex items-center gap-[6px] whitespace-nowrap text-[13px] tracking-[0.1px]">
          <Link to="/memos" className="text-subtle transition-colors hover:text-muted">
            Investment Memos
          </Link>
          {crumb && (
            <>
              <ChevronRight size={13} className="text-subtle" aria-hidden />
              <span className="text-muted">{crumb}</span>
            </>
          )}
        </nav>
        <h1 className="m-0 whitespace-nowrap text-[22px] font-normal tracking-[-0.3px] text-ink">Investment memo</h1>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-[8px]">{actions}</div>}
    </header>
  );
}

function HeaderActions() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <>
      <Button
        icon={copied ? Check : Share}
        onClick={() => {
          navigator.clipboard?.writeText(window.location.href).then(() => setCopied(true), () => undefined);
        }}
      >
        {copied ? "Link copied" : "Share"}
      </Button>
      <Button icon={Download} onClick={() => window.print()}>
        Export PDF
      </Button>
    </>
  );
}

/** Only on the exported PDF: where the memo came from and how far to trust it. */
function PrintFooter({ memo }: { memo: MemoT }) {
  const t = computeTrust(memo);
  return (
    <p className="m-0 hidden max-w-[760px] border-t border-hair pt-[10px] text-[11px] leading-[16px] tracking-[0.2px] text-subtle print:block">
      Drafted by Bellwether on {new Date(memo.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}.{" "}
      {t.withSource} of {t.total} claims have a source; {t.notVerified === 0 ? "all were checked" : `${t.notVerified} not verified`}.{" "}
      {t.disclaimer} Bellwether recommends; a person makes the call.
    </p>
  );
}

function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto">
      <div className="flex w-[760px] max-w-full flex-col gap-[12px] py-[32px]">
        <h2 className="m-0 text-[22px] font-normal tracking-[-0.2px] text-ink">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export default function Memo() {
  const { id } = useParams<{ id: string }>();
  const fundId = useActiveFundId();
  const summary = useActiveFundSummary();
  const { data, error, loading } = useApi(() => loadMemo(id, fundId), [id, fundId]);
  const memo = data?.memo ?? null;

  let body: ReactNode;
  if (loading && !data) {
    body = <div className="min-h-0 flex-1" aria-busy="true" />;
  } else if (error) {
    body = (
      <Empty title="This memo could not be loaded">
        <p className="m-0 text-[14px] tracking-[0.2px] text-muted">{error.message}</p>
      </Empty>
    );
  } else if (!memo && !id && (data?.list ?? []).length === 0 && fundId !== DEMO_FUND_ID && !summary?.has_results) {
    body = <FundEmptyState what="investment memo" />;
  } else if (!memo) {
    const list = data?.list ?? [];
    body = (
      <Empty title={id ? "No memo for this company yet" : "No memos yet"}>
        <p className="m-0 text-[14px]/[22px] tracking-[0.2px] text-muted">
          The Analyst writes a one-page memo for the best picks of each run.
          {list.length > 0 ? " These memos are ready:" : " Start a run from Research to get one."}
        </p>
        {list.map((m) => (
          <Link
            key={m.id}
            to={`/memos/${m.id}`}
            className="flex items-center justify-between rounded-[12px] p-[10px_12px] hairline transition-colors hover:bg-surface"
          >
            <span className="text-[15px] tracking-[0.2px] text-ink">{m.title}</span>
            <span className="text-[13px] tracking-[0.2px] text-predicted">{m.fit}% fit</span>
          </Link>
        ))}
      </Empty>
    );
  } else {
    body = (
      <div key={memo.id} className="flex min-h-0 flex-1 print:block">
        <div className="flex min-w-0 flex-1 justify-center overflow-y-auto px-[24px] print:block print:overflow-visible print:px-0">
          <MemoDoc memo={memo} />
        </div>
        <PrintFooter memo={memo} />
        <DecisionRail memo={memo} className="print:hidden" />
      </div>
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <Header crumb={memo?.company.name} actions={memo ? <HeaderActions /> : undefined} />
      {body}
    </MotionConfig>
  );
}
