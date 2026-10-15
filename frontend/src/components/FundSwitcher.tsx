import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { createRun } from "@/lib/api";
import { useActiveFundId, useFundRefresh, useFunds, useSetActiveFund } from "@/lib/fund";
import type { FundSummary } from "@/lib/types";
import { CompanyLogo } from "./CompanyLogo";
import { Button } from "./Button";

export type SwitcherMode = "list" | "add" | null;

/** "https://www.seedcamp.com/x" or "seedcamp.com" -> a full URL, or null if it isn't a website. */
function normaliseUrl(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  try {
    const u = new URL(/^https?:\/\//i.test(v) ? v : `https://${v}`);
    return u.hostname.includes(".") ? u.toString() : null;
  } catch {
    return null;
  }
}

function fundStatus(f: FundSummary): string {
  if (f.has_results) return "Results ready";
  if (f.latest_run_id) return "Run started";
  return "Not run yet";
}

/** The sidebar's workspace tile: shows the active fund and opens a list of every fund to switch to. */
export function FundSwitcher({
  name,
  logo,
  mode,
  onMode,
}: {
  name: string;
  logo: string | null;
  mode: SwitcherMode;
  onMode: (m: SwitcherMode) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const funds = useFunds();
  const activeId = useActiveFundId();
  const setActive = useSetActiveFund();

  useEffect(() => {
    if (!mode) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && onMode(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onMode(null);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [mode, onMode]);

  return (
    <div ref={ref} className="relative flex h-[70px] shrink-0 items-center border-b border-hair px-[8px]">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={mode !== null}
        onClick={() => onMode(mode ? null : "list")}
        className="flex min-w-0 flex-1 items-center gap-[12px] rounded-[12px] p-[8px] text-left transition-colors hover:bg-[#1A18170A]"
      >
        <CompanyLogo name={name} logo={logo} size={38} radius={10} tone="sage" className="shadow-[0_1px_3px_#1A18171A]" />
        <span className="flex min-w-0 flex-1 flex-col gap-[1px]">
          <span className="truncate text-[15px] font-medium tracking-[0.1px] text-ink">{name}</span>
          <span className="truncate text-[12px] tracking-[0.1px] text-subtle">Switch fund</span>
        </span>
        <ChevronsUpDown size={16} className="shrink-0 text-muted" aria-hidden />
      </button>

      <AnimatePresence>
        {mode && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
            className="absolute left-[12px] top-[calc(100%-4px)] z-40 flex w-[300px] flex-col rounded-[14px] bg-panel p-[6px] shadow-[0_8px_24px_#1A18171F] hairline"
          >
            <div className="p-[6px_10px_4px] text-[12px] tracking-[0.2px] text-subtle">Funds · {funds.length}</div>
            <ul role="listbox" aria-label="Funds" className="m-0 flex max-h-[320px] list-none flex-col gap-[1px] overflow-auto p-0">
              {funds.map((f) => {
                const active = f.id === activeId;
                return (
                  <li key={f.id} role="option" aria-selected={active}>
                    <button
                      type="button"
                      onClick={() => {
                        onMode(null);
                        if (!active) setActive(f.id);
                      }}
                      className={cn(
                        "flex w-full items-center gap-[10px] rounded-[10px] p-[7px_10px] text-left transition-colors hover:bg-surface",
                        active && "bg-surface",
                      )}
                    >
                      <CompanyLogo name={f.name} logo={f.logo} size={28} radius={8} tone={f.has_results ? "sage" : "grey"} />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-[14px] tracking-[0.1px] text-ink">{f.name}</span>
                        <span className="truncate text-[12px] tracking-[0.1px] text-subtle">{fundStatus(f)}</span>
                      </span>
                      {active && <Check size={15} className="shrink-0 text-predicted" aria-hidden />}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="mt-[4px] border-t border-hair pt-[4px]">
              {mode === "add" ? (
                <AddFundForm onDone={() => onMode(null)} />
              ) : (
                <button
                  type="button"
                  onClick={() => onMode("add")}
                  className="flex w-full items-center gap-[10px] rounded-[10px] p-[8px_10px] text-left text-[14px] tracking-[0.1px] text-muted transition-colors hover:bg-surface hover:text-ink"
                >
                  <Plus size={16} aria-hidden />
                  Add a fund
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Paste a fund's website: starts a live run (POST /api/runs), switches to that fund and opens Research. */
function AddFundForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const refresh = useFundRefresh();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const url = normaliseUrl(value);
    if (!url) {
      setError("That doesn’t look like a website. Try something like seedcamp.com");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await createRun({ fund_url: url, task: null });
      refresh();
      onDone();
      navigate(`/research?run=${encodeURIComponent(run.run_id)}&fund=${encodeURIComponent(run.fund_id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t start the run. Please try again.");
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-[8px] p-[8px_10px]">
      <label className="text-[12px] tracking-[0.2px] text-subtle" htmlFor="add-fund-url">
        Fund website
      </label>
      <input
        id="add-fund-url"
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="seedcamp.com"
        className="rounded-[10px] bg-track p-[8px_10px] text-[14px] text-ink outline-none placeholder:text-subtle focus:outline-2 focus:outline-sage"
      />
      {error && <span className="text-[12px] text-muted">{error}</span>}
      <Button type="submit" variant="gold" size="sm" disabled={busy}>
        {busy ? "Starting…" : "Run Bellwether on this fund"}
      </Button>
    </form>
  );
}
