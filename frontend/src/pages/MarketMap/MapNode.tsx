import { memo, useState, type CSSProperties } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { motion, useReducedMotion } from "motion/react";
import type { GraphNode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { assetUrl } from "@/lib/api";
import { FUND_SIZE, NODE_W, dotSize } from "./model";

const EASE = [0.22, 1, 0.36, 1] as const;

export type MapNodeData = {
  node: GraphNode;
  /** Seconds before this node scales in. */
  delay: number;
  dim: boolean;
  selected: boolean;
};
export type MapFlowNode = Node<MapNodeData, "company">;

/** Invisible anchor at the dot centre so straight edges meet the middle of each dot. */
function CenterHandles({ cy }: { cy: number }) {
  const style: CSSProperties = {
    top: cy,
    left: "50%",
    width: 0,
    height: 0,
    minWidth: 0,
    minHeight: 0,
    border: 0,
    background: "transparent",
    transform: "none",
  };
  return (
    <>
      <Handle type="source" position={Position.Top} isConnectable={false} style={style} />
      <Handle type="target" position={Position.Top} isConnectable={false} style={style} />
    </>
  );
}

/** One company (or the fund) on the map. Scales in from its dot centre; gold picks pulse slowly. */
function MapNodeView({ data }: NodeProps<MapFlowNode>) {
  const { node, delay, dim, selected } = data;
  const reduced = useReducedMotion();
  const size = dotSize(node);
  const isFund = node.kind === "fund";

  return (
    <div
      className="transition-opacity duration-300 ease-soft"
      style={{ width: isFund ? FUND_SIZE : NODE_W, opacity: dim ? 0.18 : 1 }}
      aria-label={node.kind === "pick" && node.fit != null ? `${node.label}, ${node.fit}% fit` : node.label}
    >
      <CenterHandles cy={size / 2} />
      <motion.div
        initial={reduced ? false : { scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.55, delay, ease: EASE }}
        style={{ transformOrigin: `50% ${size / 2}px` }}
      >
        {isFund ? <FundBubble node={node} /> : node.kind === "theme" ? <ThemeHub label={node.label} /> : <CompanyNode node={node} size={size} selected={selected} />}
      </motion.div>
    </div>
  );
}

export const MapNode = memo(MapNodeView);

/** A sector hub ("By theme" view): a soft sage dot with the theme's name. */
function ThemeHub({ label }: { label: string }) {
  return (
    <div className="flex w-[160px] flex-col items-center gap-[6px]">
      <div className="size-[44px] rounded-full bg-accent-soft" style={{ outline: "1.5px solid var(--color-accent)", outlineOffset: -0.75 }} />
      <div className="whitespace-nowrap rounded-full bg-bg p-[2px_8px] text-[13px] font-medium text-ink">{label}</div>
    </div>
  );
}

/** The fund in the middle, or the company the map is centred on (it has a company_id and is clickable). */
function FundBubble({ node }: { node: GraphNode }) {
  const label = node.label;
  const centred = node.company_id != null;
  return (
    <div
      className={cn("flex size-[120px] flex-col items-center justify-center gap-[2px] rounded-full bg-accent-soft", centred && "cursor-pointer")}
      style={{ outline: "1.5px solid var(--color-accent)", outlineOffset: -0.75 }}
    >
      <div className="max-w-[108px] truncate whitespace-nowrap text-[15px] font-medium text-ink">{label}</div>
      <div className="whitespace-nowrap text-[11px] text-muted">
        {centred ? (node.fit != null ? `centre · ${node.fit}% fit` : "centre") : "the fund"}
      </div>
    </div>
  );
}

function CompanyNode({ node, size, selected }: { node: GraphNode; size: number; selected: boolean }) {
  const isPick = node.kind === "pick";
  return (
    <div
      className={cn("flex w-[160px] flex-col items-center gap-[6px]", node.kind !== "fund" && node.company_id && "cursor-pointer")}
      aria-current={selected || undefined}
    >
      {isPick ? <PickDot /> : <CompanyDot node={node} size={size} />}
      {isPick ? (
        <div className="flex items-center gap-[6px] whitespace-nowrap rounded-full bg-predicted p-[3px_8px] text-white">
          <span className="text-[13px] font-medium">{node.label}</span>
          {node.fit != null && <span className="font-mono text-[12px] font-medium">{node.fit}%</span>}
        </div>
      ) : (
        <div
          className={cn(
            "whitespace-nowrap font-medium",
            node.kind === "competitor" ? "text-[11px] text-subtle" : "text-[13px] text-ink",
          )}
        >
          {node.label}
        </div>
      )}
    </div>
  );
}

/** Portfolio dots carry the real logo in a sage ring; competitors a small logo in a white ring.
 *  No logo (or it fails to load): a plain sage / grey dot. */
function CompanyDot({ node, size }: { node: GraphNode; size: number }) {
  const [failed, setFailed] = useState(false);
  const isComp = node.kind === "competitor";
  const showLogo = node.logo && !failed;

  if (!showLogo) {
    return (
      <div
        className="shrink-0 rounded-full"
        style={{
          width: isComp ? 22 : 26,
          height: isComp ? 22 : 26,
          background: isComp ? "var(--color-competitor)" : "var(--color-accent)",
          outline: isComp ? "1.5px solid #fff" : "2px solid #fff",
          outlineOffset: isComp ? -0.75 : -1,
        }}
      />
    );
  }
  return (
    <div
      className="shrink-0 overflow-hidden rounded-full"
      style={{
        width: size,
        height: size,
        outline: isComp ? "1.5px solid #fff" : "2.5px solid var(--color-accent)",
        outlineOffset: isComp ? -0.75 : -1.25,
      }}
    >
      <img
        src={assetUrl(node.logo)!}
        alt=""
        draggable={false}
        onError={() => setFailed(true)}
        className="size-full object-cover"
      />
    </div>
  );
}

const GLOW = "0px 0px 24px #C2862B66";
const GLOW_PEAK = "0px 0px 34px #C2862BA6";

/** Gold pick dot: 4px cream ring + soft glow that pulses every 2s. */
function PickDot() {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="size-[34px] shrink-0 rounded-full bg-predicted"
      style={{
        outline: "4px solid #F6EBD6",
        outlineOffset: -2,
        boxShadow: GLOW,
      }}
      animate={reduced ? undefined : { boxShadow: [GLOW, GLOW_PEAK, GLOW] }}
      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}
