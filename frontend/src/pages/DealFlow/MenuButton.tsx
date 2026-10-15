import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, type LucideIcon } from "lucide-react";
import { Button } from "@/components/Button";
import { cn } from "@/lib/utils";

export interface MenuOption<T extends string> {
  value: T;
  label: string;
}

interface MenuButtonProps<T extends string> {
  icon: LucideIcon;
  /** Text on the button, e.g. "Sector: All". */
  label: string;
  options: MenuOption<T>[];
  value: T;
  onChange: (value: T) => void;
  "aria-label"?: string;
}

/** White toolbar button that opens a small list of choices (Sector filter, sort order). */
export function MenuButton<T extends string>({ icon, label, options, value, onChange, ...aria }: MenuButtonProps<T>) {
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

  return (
    <div ref={ref} className="relative">
      <Button
        icon={icon}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={aria["aria-label"]}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
      </Button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            className="absolute right-0 top-[calc(100%+6px)] z-20 m-0 flex min-w-[180px] list-none flex-col gap-[2px] rounded-[12px] bg-panel p-[4px] shadow-[0_8px_24px_#1A18171F] hairline"
          >
            {options.map((o) => {
              const active = o.value === value;
              return (
                <li key={o.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    onClick={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-[12px] whitespace-nowrap rounded-[8px] p-[7px_10px] text-left text-[13px] transition-colors hover:bg-track",
                      active ? "text-ink" : "text-muted",
                    )}
                  >
                    {o.label}
                    {active && <Check size={14} className="text-accent" aria-hidden />}
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
