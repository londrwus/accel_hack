import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { prefetchCompany, prefetchPages } from "@/lib/api";
import { FundProvider, useActiveFundId, useFund } from "@/lib/fund";
import { Sidebar } from "./Sidebar";

/** Platform layout: sidebar on the shell background + white inset main panel (8px inset, radius 16, hairline).
 *  Pages render inside the panel, which is a flex column: <PageHeader/> then a `flex-1 min-h-0` body. */
export function AppShell() {
  return (
    <FundProvider>
      <ShellLayout />
    </FundProvider>
  );
}

/** Company pages load ahead: hovering or focusing any company link fetches its data. */
function prefetchFromLink(e: Event) {
  const a = (e.target as Element | null)?.closest?.("a[href*='/companies/']") as HTMLAnchorElement | null;
  if (!a) return;
  const url = new URL(a.href, window.location.origin);
  const m = url.pathname.match(/\/companies\/([^/]+)/);
  if (m) prefetchCompany(decodeURIComponent(m[1]), url.searchParams.get("fund") ?? undefined);
}

function ShellLayout() {
  const fund = useFund();
  const fundId = useActiveFundId();
  useEffect(() => {
    document.addEventListener("mouseover", prefetchFromLink, { passive: true });
    document.addEventListener("focusin", prefetchFromLink);
    return () => {
      document.removeEventListener("mouseover", prefetchFromLink);
      document.removeEventListener("focusin", prefetchFromLink);
    };
  }, []);
  useEffect(() => {
    // The main pages' data, fetched once the current page has had its turn.
    const t = window.setTimeout(() => prefetchPages(fundId), 1200);
    return () => window.clearTimeout(t);
  }, [fundId]);
  return (
    <div className="flex h-screen min-h-[720px] w-full overflow-hidden bg-shell print:block print:h-auto print:min-h-0 print:overflow-visible print:bg-panel">
      <Sidebar fund={fund} className="print:hidden" />
      <div className="flex min-w-0 flex-1 p-[8px] print:block print:p-0">
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[16px] bg-panel hairline print:block print:overflow-visible print:rounded-none print:outline-none">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
