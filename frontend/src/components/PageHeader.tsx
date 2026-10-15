import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: ReactNode;
  /** Grey line under the title (13px), or a breadcrumb node. */
  subtitle?: ReactNode;
  /** Right side: status chip + white secondary + gold primary. */
  actions?: ReactNode;
  className?: string;
}

/** Header row at the top of the white main panel (22px title, hairline below, ~84px tall). */
export function PageHeader({ title, subtitle, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("flex shrink-0 items-center justify-between border-b border-hair p-[18px_24px]", className)}>
      <div className="flex min-w-0 flex-col gap-[2px]">
        <h1 className="m-0 whitespace-nowrap text-[22px] font-normal tracking-[-0.3px] text-ink">{title}</h1>
        {subtitle != null && <div className="whitespace-nowrap text-[13px] tracking-[0.1px] text-subtle">{subtitle}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-[8px]">{actions}</div>}
    </header>
  );
}
