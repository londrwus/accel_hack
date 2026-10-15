import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface NavItemProps {
  icon: LucideIcon;
  label: ReactNode;
  /** Route. Active state comes from the router unless `active` is given. */
  to?: string;
  /** Match the route exactly (default false, so /memos is active on /memos/x). */
  end?: boolean;
  /** Force the active look (white pill). */
  active?: boolean;
  /** Glossy sage count badge, e.g. new deals. */
  badge?: number | null;
  onClick?: () => void;
  className?: string;
}

/** Glossy sage count badge (Deal Flow · 3). */
export function CountBadge({ value }: { value: number }) {
  return (
    <span className="sage-surface flex h-[22px] min-w-[22px] items-center justify-center rounded-[11px] px-[6px] text-[12px] font-semibold text-white">
      {value}
    </span>
  );
}

const itemBase =
  "flex w-full items-center gap-[12px] rounded-[12px] p-[9px_12px] text-left text-[15px] tracking-[0.1px] transition-colors";
const activeCls = "bg-panel hairline shadow-nav text-ink";
const idleCls = "text-muted hover:text-ink";

/** Sidebar navigation row: 18px thin icon + 15px label, optional count badge. */
export function NavItem({ icon: Icon, label, to, end, active, badge, onClick, className }: NavItemProps) {
  const inner = (isActive: boolean) => (
    <>
      <Icon size={18} className={isActive ? "text-ink" : "text-muted"} aria-hidden />
      <span className="flex-1 truncate">{label}</span>
      {badge != null && badge > 0 && <CountBadge value={badge} />}
    </>
  );
  if (to) {
    return (
      <NavLink
        to={to}
        end={end}
        onClick={onClick}
        className={({ isActive }) => cn(itemBase, (active ?? isActive) ? activeCls : idleCls, className)}
      >
        {({ isActive }) => inner(active ?? isActive)}
      </NavLink>
    );
  }
  return (
    <button type="button" onClick={onClick} className={cn(itemBase, active ? activeCls : idleCls, className)}>
      {inner(Boolean(active))}
    </button>
  );
}
