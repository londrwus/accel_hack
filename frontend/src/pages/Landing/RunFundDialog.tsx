import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Globe, X } from "lucide-react";
import { createRun } from "@/lib/api";
import { EASE } from "./motion";
import { Pill } from "./Pill";

const EXAMPLES = [
  { name: "LocalGlobe", url: "localglobe.vc" },
  { name: "Haatch", url: "haatch.com" },
  { name: "Seedcamp", url: "seedcamp.com" },
];

function normaliseUrl(raw: string): string | null {
  const s = raw.trim();
  if (!s) return null;
  const withScheme = /^https?:\/\//i.test(s) ? s : `https://${s}`;
  try {
    const u = new URL(withScheme);
    if (!u.hostname.includes(".")) return null;
    return u.toString();
  } catch {
    return null;
  }
}

/** "Run Bellwether on a fund": paste a fund's website, start a run, go to Research to watch it live. */
export function RunFundDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    const t = window.setTimeout(() => inputRef.current?.focus(), 60);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  async function start(raw: string) {
    const url = normaliseUrl(raw);
    if (!url) {
      setError("That doesn’t look like a website. Try something like localglobe.vc");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await createRun({ fund_url: url, task: null });
      navigate(`/research?run=${encodeURIComponent(run.run_id)}&fund=${encodeURIComponent(run.fund_id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn’t start the run. Please try again.");
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void start(value);
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-[#1A181733] px-[16px] pt-[18vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="run-fund-title"
            className="w-full max-w-[560px] rounded-[16px] bg-surface p-[28px] shadow-window outline outline-1 -outline-offset-[0.5px] outline-[#1A181714]"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.35, ease: EASE }}
          >
            <div className="flex items-start justify-between gap-[16px]">
              <h2 id="run-fund-title" className="m-0 text-[24px] font-normal tracking-[-0.4px] text-ink">
                Run Bellwether on a fund
              </h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="-m-[4px] rounded-[8px] p-[4px] text-subtle transition-colors hover:text-ink"
              >
                <X size={18} />
              </button>
            </div>
            <p className="m-0 mt-[8px] text-[15px]/[22px] tracking-[0.2px] text-muted">
              Paste the fund’s website. The analyst team reads it, finds its next deals and writes the memo. It takes about
              3 minutes.
            </p>

            <form onSubmit={onSubmit} className="mt-[20px] flex flex-wrap items-center gap-[10px] sm:flex-nowrap">
              <label className="flex min-w-0 flex-1 items-center gap-[10px] rounded-full bg-panel p-[12px_16px] outline outline-1 -outline-offset-[0.5px] outline-hair focus-within:outline-sage">
                <Globe size={16} className="shrink-0 text-subtle" aria-hidden />
                <input
                  ref={inputRef}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="localglobe.vc"
                  aria-label="Fund website"
                  inputMode="url"
                  autoComplete="url"
                  className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[16px] tracking-[0.2px] text-ink outline-none placeholder:text-subtle"
                />
              </label>
              <Pill type="submit" arrow disabled={busy}>
                {busy ? "Starting…" : "Start"}
              </Pill>
            </form>

            {error && <p className="m-0 mt-[10px] text-[14px] tracking-[0.2px] text-danger">{error}</p>}

            <div className="mt-[18px] flex flex-wrap items-center gap-[8px]">
              <span className="text-[14px] tracking-[0.2px] text-subtle">Try:</span>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.url}
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setValue(ex.url);
                    void start(ex.url);
                  }}
                  className="rounded-full bg-chip p-[4px_10px] text-[14px] tracking-[0.2px] text-ink transition-colors hover:bg-[#1A181714]"
                >
                  {ex.name}
                </button>
              ))}
            </div>

            <p className="m-0 mt-[20px] border-t border-[#E0DBD1] pt-[14px] text-[13px]/[19px] tracking-[0.2px] text-subtle">
              Uses public information only. Bellwether recommends and drafts; it never contacts founders. You make the call.
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
