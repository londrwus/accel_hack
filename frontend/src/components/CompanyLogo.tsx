import { useState } from "react";
import { cn } from "@/lib/utils";
import { assetUrl } from "@/lib/api";

/** Initial-tile colours: grey = deal / dataset row · sage = portfolio · gold = pick · competitor = rival. */
export type LogoTone = "grey" | "sage" | "gold" | "competitor";

const tones: Record<LogoTone, string> = {
  grey: "bg-chip text-muted",
  sage: "bg-accent-soft text-accent",
  gold: "bg-predicted-soft text-predicted",
  competitor: "bg-chip text-subtle",
};

export interface CompanyLogoProps {
  name: string;
  /** URL or "/logos/x.png". null -> initial tile. Never invent a logo. */
  logo?: string | null;
  /** px, default 32 (Deal Flow). Portfolio tiles use 30, sidebar fund tile 38. */
  size?: number;
  /** px, default 8. */
  radius?: number;
  tone?: LogoTone;
  className?: string;
}

/** Real logo when we have one, otherwise the first letter on a soft tile. Falls back if the image fails. */
export function CompanyLogo({ name, logo, size = 32, radius = 8, tone = "grey", className }: CompanyLogoProps) {
  const src = assetUrl(logo);
  const [broken, setBroken] = useState<string | null>(null);
  const style = { width: size, height: size, borderRadius: radius };
  if (src && broken !== src) {
    return (
      <img
        src={src}
        alt={name}
        width={size}
        height={size}
        onError={() => setBroken(src)}
        style={style}
        className={cn("shrink-0 bg-panel object-contain outline outline-1 -outline-offset-[0.5px] outline-[#1A181714]", className)}
      />
    );
  }
  return (
    <span
      aria-label={name}
      style={{ ...style, fontSize: Math.round(size * 0.44) }}
      className={cn("flex shrink-0 items-center justify-center", tones[tone], className)}
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
