import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { EASE } from "./motion";

interface FilterMenuProps<T extends string | number> {
  /** Button text when nothing is picked, e.g. "Sector". */
  label: string;
  /** First menu row that clears the filter, e.g. "Any sector". */
  anyLabel: string;
  options: T[];
  value: T | undefined;
  onChange: (value: T | undefined) => void;
  /** How a value reads in the menu and on the button. Default String(value). */
  format?: (value: T) => string;
  /** Button text for the "any" row when it is picked (e.g. "Sort: best fit"). Default `label`. */
  idleLabel?: string;
}

/** White toolbar filter (chevron + label) that opens a short list of values. */
export function FilterMenu<T extends string | number>({ label, anyLabel, options, value, onChange, format = String, idleLabel }: FilterMenuProps<T>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = value !== undefined;
  const rows: { v: T | undefined; text: string }[] = [{ v: undefined, text: anyLabel }, ...options.map((o) => ({ v: o, text: format(o) }))];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={active ? `${label}: ${format(value as T)}` : `Filter by ${label.toLowerCase()}`}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-[6px] whitespace-nowrap rounded-[12px] p-[7px_12px] text-[13px] font-medium tracking-[0.1px] shadow-btn hairline transition-opacity hover:opacity-90 active:opacity-95",
          active ? "bg-accent-soft text-accent" : "bg-panel text-ink",
        )}
      >
        <ChevronDown size={14} className={cn("transition-transform duration-200", active ? "text-accent" : "text-muted", open && "rotate-180")} aria-hidden />
        {active ? format(value as T) : (idleLabel ?? label)}
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: EASE }}
            className="absolute left-0 top-[calc(100%+6px)] z-30 m-0 flex max-h-[320px] min-w-[180px] list-none flex-col gap-[2px] overflow-auto rounded-[12px] bg-panel p-[4px] shadow-[0_8px_24px_#1A18171F] hairline"
          >
            {rows.map((r) => {
              const selected = r.v === value;
              return (
                <li key={r.text}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => {
                      onChange(r.v);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-[12px] whitespace-nowrap rounded-[8px] p-[7px_10px] text-left text-[13px] transition-colors hover:bg-track",
                      selected ? "text-ink" : "text-muted",
                    )}
                  >
                    {r.text}
                    {selected && <Check size={14} className="text-accent" aria-hidden />}
                  </button>
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
