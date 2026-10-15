import { motion, useReducedMotion } from "motion/react";
import { FileText, Scale, TriangleAlert } from "lucide-react";
import { Button } from "@/components/Button";
import type { DealFlowItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ShortlistPanelProps {
  fundName: string;
  items: DealFlowItem[];
  pickedFrom: string;
  updatedLabel: string;
  mixLabel: string;
  selectedId: string | null;
  onSelect: (companyId: string) => void;
  /** company id -> display name, for "Competes with Cleo". */
  nameOf: (companyId: string) => string;
  memoHref: (item: DealFlowItem) => string;
}

/** Right panel (360): "Next deals". The selected pick is expanded with the why, fit bars and the memo button. */
export function ShortlistPanel({
  fundName,
  items,
  pickedFrom,
  updatedLabel,
  mixLabel,
  selectedId,
  onSelect,
  nameOf,
  memoHref,
}: ShortlistPanelProps) {
  return (
    <aside className="flex h-full w-[360px] shrink-0 flex-col tracking-normal gap-[20px] overflow-y-auto border-l border-hair p-[20px]">
      <div className="flex flex-col gap-[4px]">
        <h2 className="m-0 whitespace-nowrap text-[18px] font-normal tracking-[-0.3px] text-ink">Next deals for {fundName}</h2>
        <div className="whitespace-nowrap text-[13px] text-muted">
          Picked from {pickedFrom} startups · {updatedLabel}
        </div>
      </div>

      <div className="flex flex-col">
        {items.map((item, i) => {
          const expanded = item.company.id === selectedId;
          const conflict = item.conflict_with ? `Competes with ${nameOf(item.conflict_with)}` : null;
          return expanded ? (
            <SelectedPick
              key={item.company.id}
              item={item}
              conflict={conflict}
              memoHref={memoHref(item)}
              className={cn(i > 0 && "pt-[16px]", i < items.length - 1 ? "mb-[19px]" : "mb-[-0.5px]")}
            />
          ) : (
            <PickRow key={item.company.id} item={item} conflict={conflict} onClick={() => onSelect(item.company.id)} />
          );
        })}
      </div>

      <div className="flex w-fit items-center gap-[6px] rounded-full bg-chip p-[8px_14px] text-[12px] text-muted">
        <Scale size={13} aria-hidden />
        <span className="whitespace-nowrap">{mixLabel}</span>
      </div>
    </aside>
  );
}

function ConflictFlag({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-[5px] text-[11px] text-danger">
      <TriangleAlert size={12} aria-hidden />
      <span className="whitespace-nowrap">{label}</span>
    </div>
  );
}

function SelectedPick({
  item,
  conflict,
  memoHref,
  className,
}: {
  item: DealFlowItem;
  conflict: string | null;
  memoHref: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const c = item.company;
  const meta = [c.one_liner, c.stage, c.city].filter(Boolean).join(" · ");
  return (
    <motion.section
      layout={!reduced}
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      aria-label={`${item.rank} · ${c.name}`}
      className={cn("flex flex-col gap-[10px] border-b border-[#1A18170F] pb-[20px] pt-[4px]", className)}
    >
      <div className="flex items-center justify-between">
        <div className="flex min-w-0 flex-col gap-[2px]">
          <div className="whitespace-nowrap text-[17px] font-medium text-ink">
            {item.rank} · {c.name}
          </div>
          <div className="truncate text-[13px] text-muted">{meta}</div>
          {conflict && <ConflictFlag label={conflict} />}
        </div>
        <div className="flex shrink-0 flex-col items-end">
          <div className="text-[24px] text-predicted">{item.fit}%</div>
          <div className="text-[11px] text-muted">fit</div>
        </div>
      </div>

      {item.why.map((line) => (
        <p key={line} className="m-0 text-[13px]/[19px] text-ink">
          {"—  "}
          {line}
        </p>
      ))}

      <div className="flex flex-col gap-[7px]">
        {item.fit_parts.map((p, i) => (
          <div key={p.label} className="flex items-center gap-[10px]">
            {/* The design's first label column is 110px, the others 120px. */}
            <div className={cn("shrink-0 text-[12px] text-muted", i === 0 ? "w-[110px]" : "w-[120px]")}>{p.label}</div>
            <div className="h-[6px] flex-1 overflow-hidden rounded-[3px] bg-[#1A18170F]">
              <motion.div
                className="h-full rounded-[3px] bg-predicted"
                initial={reduced ? false : { width: 0 }}
                animate={{ width: `${Math.round(Math.max(0, Math.min(1, p.value)) * 100)}%` }}
                transition={{ duration: 0.7, delay: 0.15 + i * 0.08, ease: [0.22, 1, 0.36, 1] }}
              />
            </div>
          </div>
        ))}
      </div>

      <Button variant="gold" icon={FileText} to={memoHref} className="w-full justify-center">
        Read the diligence memo
      </Button>
    </motion.section>
  );
}

function PickRow({ item, conflict, onClick }: { item: DealFlowItem; conflict: string | null; onClick: () => void }) {
  return (
      <motion.button
        layout
        type="button"
        onClick={onClick}
        className="mb-[-1px] flex w-full items-center justify-between border-b border-[#E0DBD1] py-[12px] text-left transition-opacity hover:opacity-80"
      >
        <div className="flex min-w-0 flex-col gap-[3px]">
          <div className="whitespace-nowrap text-[14px] font-medium text-ink">
            {item.rank} · {item.company.name}
          </div>
          <div className="truncate text-[12px] text-muted">{item.company.one_liner}</div>
          {conflict && <ConflictFlag label={conflict} />}
        </div>
        <div className="shrink-0 font-mono text-[14px] text-predicted">{item.fit}%</div>
      </motion.button>
  );
}
