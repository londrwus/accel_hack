import { useState } from "react";
import { ArrowRight, Download, LayoutGrid, Plus } from "lucide-react";
import { Button } from "@/components/Button";
import { NavItem } from "@/components/NavItem";
import { Badge, DealStatusBadge } from "@/components/Badge";
import { Segmented } from "@/components/Segmented";
import { Chip, LabeledChip, SourceChip } from "@/components/Chip";
import { SignalChip } from "@/components/SignalChip";
import { DataCard } from "@/components/DataCard";
import { CompanyLogo } from "@/components/CompanyLogo";
import { Sidebar } from "@/components/Sidebar";
import { FundProvider, useFund } from "@/lib/fund";

// Dev-only page (/dev/components, not in production builds) to compare with design/screens/0-components.png.
export default function ComponentsGallery() {
  return (
    <FundProvider>
      <Gallery />
    </FundProvider>
  );
}

function Gallery() {
  const fund = useFund();
  const [seg, setSeg] = useState<"all" | "new" | "under_review" | "passed">("all");
  const sectors = fund?.fund.dna?.sectors ?? [];
  return (
    <div className="flex min-h-screen gap-[48px] bg-shell p-[40px]">
      <div className="flex flex-col gap-[32px]">
        {/* Row 1 = the Components frame */}
        <div className="flex items-start gap-[48px]">
          <Button variant="gold">Run again</Button>
          <Button variant="white">Next</Button>
          <Button variant="ghost">Skip</Button>
          <NavItem icon={LayoutGrid} label="Overview" className="w-[232px]" />
          <NavItem icon={LayoutGrid} label="Overview" active className="w-[232px]" />
        </div>
        {/* Extras used across pages */}
        <div className="flex flex-wrap items-center gap-[12px]">
          <Button variant="white" icon={Download}>
            Export
          </Button>
          <Button variant="gold" icon={Plus}>
            Add company
          </Button>
          <Button variant="gold" iconRight={ArrowRight}>
            Read memo
          </Button>
          <Button size="sm" icon={Plus}>
            Save
          </Button>
          <Badge tone="sage" size="md" dot pulse>
            Working · 2m 14s
          </Badge>
          <DealStatusBadge status="new" />
          <DealStatusBadge status="under_review" />
          <DealStatusBadge status="passed" />
          <Badge tone="danger">3</Badge>
          <Badge tone="grey" size="xs">
            Seed
          </Badge>
        </div>
        <Segmented
          value={seg}
          onChange={setSeg}
          options={[
            { value: "all", label: "All", count: 61 },
            { value: "new", label: "New", count: 3 },
            { value: "under_review", label: "Under review", count: 12 },
            { value: "passed", label: "Passed", count: 46 },
          ]}
        />
        <div className="flex flex-wrap items-center gap-[6px]">
          <SignalChip signal={{ kind: "timing", label: "Raising now", icon: "trending-up" }} />
          <SignalChip signal={{ kind: "strength", label: "Like BioOrbit", icon: "link" }} />
          <SignalChip signal={{ kind: "info", label: "Hiring 3 engineers", icon: "users" }} />
          <SignalChip signal={{ kind: "risk", label: "Competes with Cleo", icon: "triangle-alert" }} />
        </div>
        <div className="flex w-[260px] flex-col gap-[8px] rounded-[14px] bg-panel p-[14px] hairline">
          <SignalChip variant="row" signal={{ kind: "risk", label: "CTO left", icon: "user-minus" }} />
          <SignalChip variant="row" signal={{ kind: "timing", label: "Likely to raise in ~3 months", icon: "trending-up" }} />
        </div>
        <div className="flex flex-wrap items-center gap-[12px]">
          <LabeledChip label="Stage:">Seed</LabeledChip>
          <LabeledChip label="Where:">Leeds, UK</LabeledChip>
          <SourceChip source={{ label: "northbeam.health", url: "https://northbeam.health", row_id: null }} />
          <SourceChip source={{ label: "", url: null, row_id: 4821 }} />
          <SourceChip source={null} verified={false} />
          <Chip strike>Gender</Chip>
          <Chip mono size="xs">
            #0193
          </Chip>
        </div>
        <div className="flex items-center gap-[12px]">
          <CompanyLogo name="Northbeam Health" />
          <CompanyLogo name="Harbor Labs" size={30} tone="sage" />
          <CompanyLogo name="Ledgerly" tone="gold" />
          <CompanyLogo name="Cleo" logo="/logos/cleo.png" size={30} />
          <CompanyLogo name="Broken" logo="/logos/nope.png" />
        </div>
        <div className="w-[392px] rounded-[16px] bg-panel p-[14px]">
          <DataCard
            title="What LocalGlobe invests in"
            segments={sectors.map((s) => ({ label: s.name, share: s.share, color: s.color, value: s.count }))}
            footer="Save to the fund profile"
          />
        </div>
      </div>
      <div className="h-[900px] rounded-[16px] bg-shell">
        <Sidebar fund={fund} />
      </div>
    </div>
  );
}
