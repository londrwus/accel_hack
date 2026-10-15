import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";

// Every route is its own chunk (React Flow only loads with the Market Map), so the first load stays small.
const Landing = lazy(() => import("@/pages/Landing"));
const DealFlow = lazy(() => import("@/pages/DealFlow"));
const Portfolio = lazy(() => import("@/pages/Portfolio"));
const Research = lazy(() => import("@/pages/Research"));
const MarketMap = lazy(() => import("@/pages/MarketMap"));
const Memo = lazy(() => import("@/pages/Memo"));
const Universe = lazy(() => import("@/pages/Universe"));
const Company = lazy(() => import("@/pages/Company"));

// Dev-only component gallery, stripped from production builds.
const ComponentsGallery = import.meta.env.DEV ? lazy(() => import("@/pages/dev/ComponentsGallery")) : null;

/** A blank panel while a page's code loads (usually a few milliseconds; the sidebar stays put). */
function page(Page: LazyExoticComponent<ComponentType>) {
  return (
    <Suspense fallback={<div className="min-h-0 flex-1" aria-busy="true" />}>
      <Page />
    </Suspense>
  );
}

/** Routes from docs/DESIGN.md. Platform pages render inside <AppShell/> (sidebar + white panel). */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={page(Landing)} />
        <Route element={<AppShell />}>
          <Route path="/deals" element={page(DealFlow)} />
          <Route path="/portfolio" element={page(Portfolio)} />
          <Route path="/research" element={page(Research)} />
          <Route path="/map" element={page(MarketMap)} />
          <Route path="/memos" element={page(Memo)} />
          <Route path="/memos/:id" element={page(Memo)} />
          <Route path="/universe" element={page(Universe)} />
          <Route path="/companies/:id" element={page(Company)} />
        </Route>
        {ComponentsGallery && <Route path="/dev/components" element={page(ComponentsGallery)} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
