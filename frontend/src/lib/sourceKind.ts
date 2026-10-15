import {
  AtSign,
  Banknote,
  ChartColumn,
  Database,
  Globe,
  Landmark,
  Link2,
  Newspaper,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Source } from "@/lib/types";

/** What kind of place a memo claim comes from. Used to group the memo's evidence. */
export type SourceKind = "news" | "filing" | "website" | "dataset" | "market" | "funding" | "people" | "social" | "other";

/** The backend may later tag sources itself; until then we guess from the label and URL. */
export type SourceWithKind = Source & { kind?: string | null };

export interface SourceKindMeta {
  kind: SourceKind;
  /** Group header, e.g. "News". */
  label: string;
  /** Short label for the filter, e.g. "Filings". */
  short: string;
  icon: LucideIcon;
}

export const SOURCE_KINDS: Record<SourceKind, SourceKindMeta> = {
  website: { kind: "website", label: "Company website", short: "Website", icon: Globe },
  dataset: { kind: "dataset", label: "Our dataset", short: "Dataset", icon: Database },
  filing: { kind: "filing", label: "Official filings", short: "Filings", icon: Landmark },
  news: { kind: "news", label: "News and blogs", short: "News", icon: Newspaper },
  funding: { kind: "funding", label: "Funding and investors", short: "Funding", icon: Banknote },
  market: { kind: "market", label: "Market data and reports", short: "Market", icon: ChartColumn },
  people: { kind: "people", label: "Team and people", short: "Team", icon: Users },
  social: { kind: "social", label: "Social media", short: "Social", icon: AtSign },
  other: { kind: "other", label: "Other sources", short: "Other", icon: Link2 },
};

/** Display order of the groups. */
export const SOURCE_KIND_ORDER: SourceKind[] = ["website", "dataset", "filing", "news", "funding", "market", "people", "social", "other"];

const FILING = /(company-information\.service\.gov\.uk|companieshouse|companies-house|sec\.gov|opencorporates|edgar|form[\s-]?d\b|registry|register|handelsregister|infogreffe|pappers|kvk\.nl|bundesanzeiger)/i;
const NEWS = /(techcrunch|sifted|ft\.com|reuters|bloomberg|theguardian|bbc\.|cnbc|forbes|wired|venturebeat|businessinsider|uktech|eu-startups|tech\.eu|thenextweb|axios|wsj\.com|nytimes|cityam|news|press|medium\.com|substack|\/blog\b|\/blog\/|\/news\/)/i;
const SOCIAL = /(linkedin\.com|(^|\/\/|\.)x\.com|twitter\.com|facebook\.com|instagram\.com|youtube\.com|threads\.net|bsky|github\.com|producthunt)/i;
const PEOPLE = /(linkedin\.com\/in\/|\bteam\b|\bfounders?\b|\bceo\b|\/about\b|\/people\b)/i;
const FUNDING = /(crunchbase|dealroom|pitchbook|cbinsights|tracxn|beauhurst|angel\.co|wellfound|seedrs|crowdcube|\binvestors?\b|\bfunding\b)/i;
const MARKET = /(statista|gartner|mckinsey|cbinsights\.com\/research|grandviewresearch|marketsandmarkets|ons\.gov\.uk|\.gov\b|\.gov\.uk|gov\.uk|nhs\.uk|europa\.eu|oecd|worldbank|eurostat|\bmarket\b|\breport\b|\bsurvey\b|\bstatistics?\b)/i;

function host(s: string | null | undefined): string {
  if (!s) return "";
  const m = s.trim().toLowerCase().match(/^(?:[a-z]+:\/\/)?(?:www\.)?([^/\s?#]+)/);
  return m ? m[1] : "";
}

function fromHint(hint: string): SourceKind | null {
  const h = hint.toLowerCase().replace(/[^a-z]/g, "");
  if (!h) return null;
  if (h.startsWith("news") || h === "press" || h === "blog") return "news";
  if (h.startsWith("filing") || h === "registry" || h === "companieshouse" || h === "sec") return "filing";
  if (h.startsWith("website") || h === "company" || h === "companywebsite") return "website";
  if (h.startsWith("dataset") || h === "data" || h === "row") return "dataset";
  if (h.startsWith("market") || h === "report") return "market";
  if (h.startsWith("fund") || h.startsWith("investor")) return "funding";
  if (h.startsWith("team") || h.startsWith("people") || h.startsWith("founder")) return "people";
  if (h.startsWith("social")) return "social";
  if (h === "other") return "other";
  return null;
}

/** Guess the kind of a claim's source. `companyWebsite` is the company's own domain, e.g. "northbeam.health". */
export function sourceKind(source: SourceWithKind | null | undefined, companyWebsite?: string | null): SourceKind | null {
  if (!source) return null;
  if (source.kind) {
    const k = fromHint(source.kind);
    if (k) return k;
  }
  const label = source.label ?? "";
  const url = source.url ?? "";
  const text = `${url} ${label}`;
  if (source.row_id != null || /^dataset\b/i.test(label)) return "dataset";
  if (FILING.test(text)) return "filing";
  const own = host(companyWebsite);
  const h = host(url) || host(label);
  if (own && h && (h === own || h.endsWith(`.${own}`))) {
    return /\/(blog|news)\b/i.test(url) ? "news" : "website";
  }
  if (PEOPLE.test(text)) return "people";
  if (SOCIAL.test(text)) return "social";
  if (FUNDING.test(text)) return "funding";
  if (NEWS.test(text)) return "news";
  if (MARKET.test(text)) return "market";
  return "other";
}
