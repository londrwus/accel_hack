import { memo } from "react";
import { EdgeLabelRenderer, type Edge, type EdgeProps } from "@xyflow/react";
import { motion, useReducedMotion } from "motion/react";
import type { EdgeKind } from "@/lib/types";
import { EDGE_STYLE } from "./model";

export type MapEdgeData = { kind: EdgeKind; delay: number; dim: boolean; label?: string | null };
export type MapFlowEdge = Edge<MapEdgeData, "line">;

/** Straight line between two dot centres that draws itself in once both ends have appeared. */
function MapEdgeView({ sourceX, sourceY, targetX, targetY, data }: EdgeProps<MapFlowEdge>) {
  const reduced = useReducedMotion();
  if (!data) return null;
  const { stroke, width } = EDGE_STYLE[data.kind];
  return (
    <>
    <motion.path
      d={`M${sourceX} ${sourceY} L${targetX} ${targetY}`}
      fill="none"
      stroke={stroke}
      strokeWidth={width}
      initial={reduced ? false : { pathLength: 0 }}
      animate={{ pathLength: 1, opacity: data.dim ? 0.15 : 1 }}
      transition={{
        pathLength: { duration: 0.6, delay: Math.min(data.delay, 1.2), ease: [0.22, 1, 0.36, 1] },
        opacity: { duration: 0.3 },
      }}
    />
    {data.label && !data.dim && (
      <EdgeLabelRenderer>
        <div
          className="pointer-events-none absolute whitespace-nowrap rounded-full bg-panel px-[5px] text-[10px] leading-[14px] text-subtle"
          style={{ transform: `translate(-50%, -50%) translate(${(sourceX + targetX) / 2}px, ${(sourceY + targetY) / 2}px)` }}
        >
          {data.label}
        </div>
      </EdgeLabelRenderer>
    )}
    </>
  );
}

export const MapEdge = memo(MapEdgeView);
