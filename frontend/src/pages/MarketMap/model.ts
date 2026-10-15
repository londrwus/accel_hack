// Shared bits for the Market Map page: filter values, node geometry and the scale-in timeline.
import type { EdgeKind, GraphNode, NodeKind } from "@/lib/types";

export type MapFilter = "all" | "owned" | "competitors" | "picks";

export const MAP_FILTERS: { value: MapFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "owned", label: "Owned" },
  { value: "competitors", label: "Competitors" },
  { value: "picks", label: "Picks" },
];

/** The node map is drawn on an 800×800 design canvas (x, y in map.json are in this space). */
export const DESIGN_W = 800;
export const DESIGN_H = 800;

/** Node box width (fund node is a 120px circle). */
export const NODE_W = 160;
export const FUND_SIZE = 120;

/** Dot diameter per node, used to put the edge anchor at the dot centre. */
export function dotSize(node: GraphNode): number {
  switch (node.kind) {
    case "fund":
      return FUND_SIZE;
    case "competitor":
      return 22;
    case "pick":
      return 34;
    case "portfolio":
      return node.logo ? 34 : 26;
    case "theme":
      return 44;
  }
}

/** Node paint order: competitors at the back, then portfolio, picks, and the fund on top. */
export const KIND_ORDER: Record<NodeKind, number> = { competitor: 0, theme: 1, portfolio: 1, pick: 2, fund: 3 };

/** Edge paint order: faint lines first, the red clash last. */
export const EDGE_ORDER: Record<EdgeKind, number> = { candidate: 0, competes: 1, owns: 2, similar: 3, conflict: 4 };

export const EDGE_STYLE: Record<EdgeKind, { stroke: string; width: number }> = {
  owns: { stroke: "#4F6F5840", width: 1.5 },
  competes: { stroke: "#A3A8B366", width: 1 },
  similar: { stroke: "#C2862B99", width: 1.5 },
  candidate: { stroke: "#C2862B33", width: 1 },
  conflict: { stroke: "#B4432A", width: 2 },
};

/** Scale-in timeline (seconds): the fund, then portfolio → competitors → picks. */
export function appearDelays(nodes: GraphNode[]): Map<string, number> {
  const start: Record<NodeKind, number> = { fund: 0, theme: 0.1, portfolio: 0.2, competitor: 0.6, pick: 1.0 };
  const step: Record<NodeKind, number> = { fund: 0, theme: 0.05, portfolio: 0.06, competitor: 0.035, pick: 0.06 };
  const seen: Record<NodeKind, number> = { fund: 0, theme: 0, portfolio: 0, competitor: 0, pick: 0 };
  const out = new Map<string, number>();
  for (const n of nodes) {
    out.set(n.id, start[n.kind] + step[n.kind] * seen[n.kind]++);
  }
  return out;
}

/** Which nodes stay bright under each filter. The fund is always shown. */
export function visibleIds(filter: MapFilter, nodes: GraphNode[], links: { source: string; target: string }[]): Set<string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ids = new Set<string>();
  for (const n of nodes) {
    const show =
      n.kind === "fund" ||
      filter === "all" ||
      (filter === "owned" && n.kind === "portfolio") ||
      (filter === "competitors" && (n.kind === "portfolio" || n.kind === "competitor")) ||
      (filter === "picks" && n.kind === "pick");
    if (show) ids.add(n.id);
  }
  if (filter === "picks") {
    // Keep the portfolio companies each pick is linked to (Like BioOrbit, Competes with Cleo).
    for (const e of links) {
      if (byId.get(e.source)?.kind === "pick") ids.add(e.target);
      if (byId.get(e.target)?.kind === "pick") ids.add(e.source);
    }
  }
  return ids;
}
