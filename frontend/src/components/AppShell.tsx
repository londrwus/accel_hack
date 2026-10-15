import { Outlet } from "react-router-dom";
import { FundProvider, useFund } from "@/lib/fund";
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

function ShellLayout() {
  const fund = useFund();
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
