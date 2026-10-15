import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ReactFlow, type NodeMouseHandler, type Viewport } from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { MapEdge, type MapFlowEdge } from "./MapEdge";
import { MapNode, type MapFlowNode } from "./MapNode";
import { DESIGN_H, DESIGN_W, EDGE_ORDER, KIND_ORDER, appearDelays, visibleIds, type MapFilter } from "./model";

const nodeTypes = { company: MapNode };
const edgeTypes = { line: MapEdge };

export interface MapCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  filter: MapFilter;
  selectedId: string | null;
  onSelectPick: (companyId: string) => void;
}

/** 1:1 at the design size; scaled down to fit (and centred) when the canvas is smaller or larger. */
type Box = { x0: number; y0: number; x1: number; y1: number };
const DESIGN_BOX: Box = { x0: 0, y0: 0, x1: DESIGN_W, y1: DESIGN_H };

/** The nodes' extent, never smaller than the design canvas (views with many picks spill past it). */
function extent(nodes: GraphNode[]): Box {
  const b = { ...DESIGN_BOX };
  for (const n of nodes) {
    b.x0 = Math.min(b.x0, n.x - 10);
    b.y0 = Math.min(b.y0, n.y - 10);
    b.x1 = Math.max(b.x1, n.x + 170);
    b.y1 = Math.max(b.y1, n.y + 70);
  }
  return b;
}

function fitViewport(w: number, h: number, b: Box = DESIGN_BOX): Viewport {
  const bw = b.x1 - b.x0;
  const bh = b.y1 - b.y0;
  let zoom = Math.min(w / bw, h / bh, 1.2);
  if (zoom > 0.97 && zoom < 1.03) zoom = 1; // stay crisp at 1440×900 (canvas is ~800×799)
  return {
    x: Math.round((w - bw * zoom) / 2 - b.x0 * zoom),
    y: Math.round((h - bh * zoom) / 2 - b.y0 * zoom),
    zoom,
  };
}

/** The node map: fund in the centre, portfolio around it, competitors outside, gold picks with a fit pill. */
export function MapCanvas({ nodes, edges, filter, selectedId, onSelectPick }: MapCanvasProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });

  const box = useMemo(() => extent(nodes), [nodes]);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const fit = () => setViewport(fitViewport(el.clientWidth, el.clientHeight, box));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [box]);

  const delays = useMemo(() => appearDelays(nodes), [nodes]);
  const visible = useMemo(() => visibleIds(filter, nodes, edges), [filter, nodes, edges]);

  const flowNodes = useMemo<MapFlowNode[]>(
    () =>
      [...nodes]
        .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind])
        .map((n) => ({
          id: n.id,
          type: "company",
          position: { x: n.x, y: n.y },
          data: {
            node: n,
            delay: delays.get(n.id) ?? 0,
            dim: !visible.has(n.id),
            selected: n.company_id != null && n.company_id === selectedId,
          },
          draggable: false,
          selectable: false,
          connectable: false,
          focusable: n.company_id != null,
          ariaRole: n.company_id != null ? "button" : "group",
        })),
    [nodes, delays, visible, selectedId],
  );

  const flowEdges = useMemo<MapFlowEdge[]>(
    () =>
      [...edges]
        .sort((a, b) => EDGE_ORDER[a.kind] - EDGE_ORDER[b.kind])
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: "line",
          selectable: false,
          focusable: false,
          data: {
            kind: e.kind,
            label: e.label,
            delay: Math.max(delays.get(e.source) ?? 0, delays.get(e.target) ?? 0) + 0.05,
            dim: !(visible.has(e.source) && visible.has(e.target)),
          },
        })),
    [edges, delays, visible],
  );

  const navigate = useNavigate();
  // A pick's first click highlights it (and what it looks like); a second click, or any other company, opens its page.
  const onNodeClick: NodeMouseHandler<MapFlowNode> = (_, n) => {
    const g = n.data.node;
    if (!g.company_id) return;
    if (g.kind === "pick" && g.company_id !== selectedId) onSelectPick(g.company_id);
    else navigate(`/companies/${encodeURIComponent(g.company_id)}`);
  };

  return (
    <div ref={wrapRef} className="relative h-full min-w-0 flex-1 overflow-hidden bg-panel tracking-normal">
      <ReactFlow<MapFlowNode, MapFlowEdge>
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        viewport={viewport}
        onViewportChange={setViewport}
        onNodeClick={onNodeClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        zoomOnPinch
        panOnDrag
        minZoom={0.4}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        aria-label="Market map"
      />
      <Legend />
    </div>
  );
}

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-[25px] left-[20px] z-10 flex items-center gap-[18px] rounded-full bg-bg p-[10px_18px] text-[12px] text-muted">
      <LegendItem label="The fund">
        <span
          className="size-[12px] rounded-full bg-accent-soft"
          style={{ outline: "1px solid var(--color-accent)", outlineOffset: -0.5 }}
        />
      </LegendItem>
      <LegendItem label="Already owns">
        <span className="size-[12px] rounded-full bg-accent" />
      </LegendItem>
      <LegendItem label="Competitor">
        <span className="size-[10px] rounded-full bg-competitor" />
      </LegendItem>
      <LegendItem label="Bellwether’s next pick">
        <span className="size-[12px] rounded-full bg-predicted" />
      </LegendItem>
      <LegendItem label="Clashes with a portfolio company">
        <span className="h-[2px] w-[16px] bg-danger" />
      </LegendItem>
    </div>
  );
}

function LegendItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex shrink-0 items-center gap-[6px] whitespace-nowrap">
      {children}
      <span>{label}</span>
    </div>
  );
}
