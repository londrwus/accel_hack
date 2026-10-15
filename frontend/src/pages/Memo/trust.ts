import type { Claim, Memo } from "@/lib/types";

/** What the "Can you trust this memo?" box shows. Counts come from the claims on the page, not from a stored summary,
 *  so the box can never disagree with the memo above it. */
export interface TrustView {
  withSource: number;
  total: number;
  notVerified: number;
  checkedByCritic: boolean;
  conflicts: string[];
  neverUsed: string[];
  disclaimer: string;
}

/** A claim counts as sourced only if it is verified and points at a URL or a dataset row. */
export function isSourced(claim: Claim): boolean {
  return claim.verified && claim.source != null && (claim.source.url != null || claim.source.row_id != null || !!claim.source.label);
}

/** The claim points at a URL or a dataset row (whether or not the Critic could confirm it). */
export function hasSource(claim: Claim): boolean {
  return claim.source != null && (claim.source.url != null || claim.source.row_id != null || !!claim.source.label);
}

export function computeTrust(memo: Memo): TrustView {
  const claims = memo.sections.flatMap((s) => s.claims);
  return {
    withSource: claims.filter(hasSource).length,
    total: claims.length,
    notVerified: claims.filter((c) => !isSourced(c)).length,
    checkedByCritic: memo.trust?.checked_by_critic ?? false,
    conflicts: memo.trust?.conflicts ?? [],
    neverUsed: memo.trust?.never_used ?? [],
    disclaimer: memo.trust?.disclaimer ?? "Public sources only. Not investment advice.",
  };
}
