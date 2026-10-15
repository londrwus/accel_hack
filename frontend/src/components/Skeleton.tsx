/** Grey placeholder rows shown while a page loads (instead of a bare "Loading…" line). */
export function SkeletonRows({ rows = 6, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="flex flex-col gap-[12px]" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-[12px]">
          <div className="h-[32px] w-[32px] shrink-0 animate-pulse rounded-[8px] bg-[#1A18170D]" />
          <div className="flex min-w-0 flex-1 flex-col gap-[6px]">
            <div className="h-[10px] animate-pulse rounded-full bg-[#1A18170F]" style={{ width: `${40 + ((i * 17) % 35)}%` }} />
            <div className="h-[8px] animate-pulse rounded-full bg-[#1A18170A]" style={{ width: `${55 + ((i * 23) % 30)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
