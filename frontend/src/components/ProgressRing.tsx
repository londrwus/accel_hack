import { cn } from "@/lib/utils";

export interface ProgressRingProps {
  done: number;
  total: number;
  /** px, default 18 (watch card). */
  size?: number;
  /** px, default size / 8 (2.25 at 18px). */
  thickness?: number;
  /** CSS colour of the arc. Default sage accent. */
  color?: string;
  className?: string;
}

/** Thin progress ring that fills clockwise from the top. */
export function ProgressRing({ done, total, size = 18, thickness, color = "var(--color-accent)", className }: ProgressRingProps) {
  const t = thickness ?? size / 8;
  const r = (size - t) / 2;
  const c = 2 * Math.PI * r;
  const frac = total > 0 ? Math.min(1, Math.max(0, done / total)) : 0;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={cn("shrink-0 -rotate-90", className)}
      role="img"
      aria-label={`${done} of ${total}`}
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1A18171A" strokeWidth={t} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={t}
        strokeDasharray={`${c * frac} ${c}`}
        style={{ transition: "stroke-dasharray 600ms cubic-bezier(0.22, 1, 0.36, 1)" }}
      />
    </svg>
  );
}
