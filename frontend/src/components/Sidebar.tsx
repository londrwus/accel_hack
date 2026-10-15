import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  BriefcaseBusiness,
  ChevronUp,
  ChevronsUpDown,
  Database,
  Eye,
  FileText,
  Inbox,
  Plus,
  Search,
  ShieldCheck,
  Sunrise,
  Waypoints,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { setWatch } from "@/lib/api";
import { useActiveFundId, useActiveFundSummary, useFundRefresh, useFunds, useSetActiveFund } from "@/lib/fund";
import type { FundResponse } from "@/lib/types";
import { Button } from "./Button";
import { FundSwitcher, type SwitcherMode } from "./FundSwitcher";
import { NavItem } from "./NavItem";
import { ProgressRing } from "./ProgressRing";

export const NAV = [
  { to: "/deals", label: "Deal Flow", icon: Inbox },
  { to: "/portfolio", label: "Portfolio", icon: BriefcaseBusiness },
  { to: "/map", label: "Market Map", icon: Waypoints },
  { to: "/memos", label: "Investment Memos", icon: FileText },
  { to: "/research", label: "Research", icon: Activity },
  { to: "/universe", label: "Startup Universe", icon: Database },
] as const;

export interface SidebarProps {
  fund: FundResponse | null;
  /** Called by "+ Add a fund". Default: open the fund switcher's "Add a fund" form. */
  onAddFund?: () => void;
  className?: string;
}

/** 264px sidebar on the shell background: workspace, search, nav, funds you cover, watch card, profile. */
export function Sidebar({ fund, onAddFund, className }: SidebarProps) {
  const [fundsOpen, setFundsOpen] = useState(true);
  const [switcher, setSwitcher] = useState<SwitcherMode>(null);
  const activeId = useActiveFundId();
  const summary = useActiveFundSummary();
  const setActive = useSetActiveFund();
  const listed = useFunds();
  const current = fund?.fund.id === activeId ? fund : null;
  const name =
    summary?.name ?? current?.fund.name ?? activeId.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  const logo = summary?.logo ?? current?.fund.logo ?? null;
  const funds = listed.length > 0 ? listed : (fund?.covered_funds ?? []);
  // The active fund always shows; one more row, then "All N funds" (opens the switcher).
  const shown = [...funds.filter((f) => f.id === activeId), ...funds.filter((f) => f.id !== activeId)].slice(0, 2);

  return (
    <aside className={cn("flex h-full w-[264px] shrink-0 flex-col border-r border-hair", className)}>
      {/* Workspace: the active fund, click to switch */}
      <FundSwitcher name={name} logo={logo} mode={switcher} onMode={setSwitcher} />

      {/* Search + Fund nav */}
      <nav className="flex shrink-0 flex-col gap-[2px] p-[16px_16px_8px_16px]">
        <SearchField />
        <div className="p-[16px_12px_6px_12px] text-[13px] tracking-[0.2px] text-subtle">Fund</div>
        {NAV.map((item) => (
          <NavItem
            key={item.to}
            to={item.to}
            icon={item.icon}
            label={item.label}
            badge={item.to === "/deals" ? current?.new_deals : undefined}
          />
        ))}
      </nav>

      {/* Funds you cover */}
      <div className="-mt-px flex shrink-0 flex-col gap-[2px] border-t border-hair p-[12px_16px]">
        <button
          type="button"
          onClick={() => setFundsOpen((o) => !o)}
          className="flex items-center justify-between p-[4px_12px_6px_12px] text-[13px] tracking-[0.2px] text-subtle"
        >
          Funds you cover
          <ChevronUp size={15} className={cn("transition-transform", !fundsOpen && "rotate-180")} />
        </button>
        {fundsOpen && (
          <>
            {shown.map((f) => (
              <NavItem key={f.id} icon={Eye} label={f.name} active={f.id === activeId} onClick={() => f.id !== activeId && setActive(f.id)} />
            ))}
            {funds.length > shown.length ? (
              <NavItem icon={ChevronsUpDown} label={`All ${funds.length} funds · add one`} onClick={() => setSwitcher("list")} />
            ) : (
              <NavItem icon={Plus} label="Add a fund" onClick={onAddFund ?? (() => setSwitcher("add"))} />
            )}
          </>
        )}
      </div>

      <div className="min-h-0 flex-1" />

      {/* Watch card, trust, profile */}
      <div className="flex shrink-0 flex-col gap-[4px] p-[0_16px_12px_16px]">
        <WatchCard fund={current} />
        <NavItem icon={ShieldCheck} label="Trust & safety" />
        <div className="flex items-center gap-[12px] p-[8px]">
          <span className="flex size-[36px] items-center justify-center rounded-full bg-avatar text-[13px] text-ink">AK</span>
          <div className="flex flex-col gap-[1px]">
            <span className="text-[15px] font-medium tracking-[0.1px] text-ink">Alex Kim</span>
            <span className="text-[12px] tracking-[0.1px] text-subtle">Partner · Plan &amp; billing</span>
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Grey search field with a "/" key hint. Enter searches the Startup Universe. */
function SearchField() {
  const navigate = useNavigate();
  const ref = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || t?.closest("input, textarea, [contenteditable=true]")) return;
      e.preventDefault();
      ref.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    navigate(q.trim() ? `/universe?q=${encodeURIComponent(q.trim())}` : "/universe");
  };

  return (
    <form onSubmit={submit} className="flex items-center gap-[10px] rounded-[12px] bg-track p-[9px_10px_9px_12px]">
      <Search size={16} className="shrink-0 text-subtle" aria-hidden />
      <input
        ref={ref}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search companies"
        aria-label="Search companies"
        className="min-w-0 flex-1 bg-transparent p-0 text-[14px] tracking-[0.1px] text-ink outline-none placeholder:text-subtle"
      />
      <kbd className="flex size-[22px] shrink-0 items-center justify-center rounded-[6px] bg-panel font-mono text-[12px] text-muted hairline">
        /
      </kbd>
    </form>
  );
}

/** "The always-on analyst": next scheduled run, Run now, progress ring, Details. */
function WatchCard({ fund }: { fund: FundResponse | null }) {
  const navigate = useNavigate();
  const refreshFund = useFundRefresh();
  const [busy, setBusy] = useState(false);
  const watch = fund?.watch;

  const runNow = async () => {
    if (!fund || busy) return;
    setBusy(true);
    try {
      const res = await setWatch(fund.fund.id, { enabled: true, simulate_next_run: true });
      refreshFund();
      navigate(res.run_id ? `/research?run=${encodeURIComponent(res.run_id)}` : "/research");
    } catch (e) {
      // Backend unreachable or busy: show the latest run rather than failing silently.
      console.warn("[watch] could not start a run", e);
      navigate("/research");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-[16px] bg-panel shadow-card">
      {/* The .pen calls this a mesh-gradient art area, but the exported PNG renders it plain white; we match the PNG. */}
      <div className="flex h-[80px] shrink-0 flex-col items-center justify-center gap-[8px]">
        <span className="flex size-[34px] items-center justify-center rounded-full bg-panel shadow-[0_2px_6px_#1A18171A]">
          <Sunrise size={17} className="text-predicted" aria-hidden />
        </span>
        <Button variant="gold" size="sm" onClick={runNow} disabled={busy}>
          Run now
        </Button>
      </div>
      <div className="flex flex-col gap-[4px] p-[12px_14px]">
        <span className="whitespace-nowrap text-[15px] font-medium tracking-[0.1px] text-ink">
          Next update: {watch?.next_run_label ?? "7:00 tomorrow"}
        </span>
        <span className="text-[12px] tracking-[0.1px] text-muted">
          {watch && !watch.enabled
            ? "Press Run now to start daily checks of this fund."
            : "Your analysts re-check the market every morning."}
        </span>
        <div className="flex items-center justify-between pt-[6px]">
          <div className="flex items-center gap-[8px]">
            <ProgressRing done={watch?.progress_done ?? 0} total={watch?.progress_total ?? 7} />
            <span className="text-[13px] tracking-[0.1px] text-muted">
              {watch?.progress_done ?? 0} of {watch?.progress_total ?? 7}
            </span>
          </div>
          <Button size="sm" to="/research">
            Details
          </Button>
        </div>
      </div>
    </div>
  );
}
