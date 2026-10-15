import { useEffect, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { CalendarCheck, Check } from "lucide-react";
import { Button } from "@/components/Button";
import { Chip } from "@/components/Chip";
import { DEMO_RUN_ID, sendFeedback } from "@/lib/api";
import { useFund } from "@/lib/fund";
import type { Memo, Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EASE } from "./MemoDoc";
import { computeTrust } from "./trust";

const DONE_LABEL: Record<Verdict, string> = {
  meeting: "Moved to first meeting",
  pass: "Passed",
  dig_deeper: "Digging deeper",
};

function Decision({ memo }: { memo: Memo }) {
  const fund = useFund();
  const [verdict, setVerdict] = useState<Verdict | null>(memo.decision);
  const [saving, setSaving] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setVerdict(memo.decision), [memo.id, memo.decision]);

  async function decide(v: Verdict) {
    if (saving) return;
    setSaving(v);
    setError(null);
    try {
      // Only records the decision. Bellwether never contacts founders.
      await sendFeedback(fund?.latest_run_id ?? DEMO_RUN_ID, { company_id: memo.company.id, verdict: v, note: null });
      setVerdict(v);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save your decision");
    } finally {
      setSaving(null);
    }
  }

  const chosen = (v: Verdict) => verdict === v;

  return (
    <section className="flex w-full flex-col gap-[12px] py-[4px]">
      <h2 className="m-0 whitespace-nowrap text-[22px] font-normal tracking-[-0.2px] text-ink">Your decision</h2>
      <p className="m-0 text-[13px]/[20px] tracking-[0.2px] text-muted">
        Bellwether recommends. You decide. Your answer teaches Bellwether for tomorrow’s run.
      </p>
      <Button
        variant="gold"
        icon={chosen("meeting") ? Check : CalendarCheck}
        className="w-full justify-center"
        aria-pressed={chosen("meeting")}
        disabled={saving != null}
        onClick={() => decide("meeting")}
      >
        {chosen("meeting") ? DONE_LABEL.meeting : "Move to first meeting"}
      </Button>
      <div className="flex w-full gap-[8px]">
        {(["pass", "dig_deeper"] as const).map((v) => (
          <Button
            key={v}
            variant="white"
            icon={chosen(v) ? Check : undefined}
            className={cn("flex-1 justify-center", chosen(v) && "bg-surface")}
            aria-pressed={chosen(v)}
            disabled={saving != null}
            onClick={() => decide(v)}
          >
            {chosen(v) ? DONE_LABEL[v] : v === "pass" ? "Pass" : "Dig deeper"}
          </Button>
        ))}
      </div>
      {(verdict || error) && (
        <motion.p
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
          className={cn("m-0 text-[12px] tracking-[0.2px]", error ? "text-danger" : "text-subtle")}
        >
          {error ?? "Saved. Tomorrow’s run will learn from this. Nobody has been contacted."}
        </motion.p>
      )}
    </section>
  );
}

function TrustRow({ label, value, tone = "good", delay }: { label: string; value: ReactNode; tone?: "good" | "warn" | "bad"; delay: number }) {
  return (
    <div className="flex h-[34px] w-full shrink-0 items-start justify-between gap-[12px] border-b border-[#1A18170F] py-[8px]">
      <span className="whitespace-nowrap text-[14px] tracking-[0.2px] text-muted">{label}</span>
      <motion.span
        initial={{ opacity: 0, scale: 0.7 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 480, damping: 22, delay }}
        className={cn(
          "origin-right text-right text-[14px] tracking-[0.2px]",
          tone === "good" ? "text-accent" : tone === "warn" ? "text-warning" : "text-danger",
        )}
      >
        {value}
      </motion.span>
    </div>
  );
}

function Trust({ memo }: { memo: Memo }) {
  const t = computeTrust(memo);
  const start = 0.5;
  const step = 0.14;
  return (
    <section className="flex w-full flex-col gap-[14px] py-[4px]">
      <h2 className="m-0 whitespace-nowrap text-[22px] font-normal tracking-[-0.2px] text-ink">Can you trust this memo?</h2>
      <TrustRow
        label="Claims with a source"
        value={`${t.withSource} of ${t.total}`}
        tone={t.withSource * 2 >= t.total ? "good" : "warn"}
        delay={start}
      />
      <TrustRow
        label="Checked by Critic"
        value={t.checkedByCritic ? "Yes" : "Not yet"}
        tone={t.checkedByCritic ? "good" : "warn"}
        delay={start + step}
      />
      <TrustRow
        label="Not verified"
        value={t.notVerified === 0 ? "None" : `${t.notVerified} ${t.notVerified === 1 ? "claim" : "claims"}`}
        tone={t.notVerified === 0 ? "good" : "warn"}
        delay={start + step * 2}
      />
      <TrustRow
        label="Clashes with portfolio"
        value={t.conflicts.length === 0 ? "None" : t.conflicts.join(", ")}
        tone={t.conflicts.length === 0 ? "good" : "bad"}
        delay={start + step * 3}
      />
      {t.neverUsed.length > 0 && (
        <>
          <div className="whitespace-nowrap text-[12px] tracking-[0.4px] text-subtle">Never used to score</div>
          <div className="flex flex-wrap items-start gap-[6px]">
            {t.neverUsed.map((f) => (
              <Chip key={f} size="sm" title={`${f} is never used to score a company`}>
                {f}
              </Chip>
            ))}
          </div>
        </>
      )}
      <div className="text-[12px] tracking-[0.2px] text-subtle">{t.disclaimer}</div>
    </section>
  );
}

/** Right rail (340): the partner's decision and the trust check. */
export function DecisionRail({ memo, className }: { memo: Memo; className?: string }) {
  return (
    <aside className={cn("flex w-[340px] shrink-0 flex-col gap-[20px] overflow-y-auto border-l border-hair p-[20px] pl-[19px]", className)}>
      <Decision memo={memo} />
      <Trust memo={memo} />
    </aside>
  );
}
