import { useCallback, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { MotionConfig, motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { Sprout } from "lucide-react";
import { DEMO_RUN_ID, getFund } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { CountUp } from "./Landing/CountUp";
import { Headline } from "./Landing/Headline";
import { FADE_START, FADE_STEP, fadeUp } from "./Landing/motion";
import { Pill } from "./Landing/Pill";
import { ProductWindow } from "./Landing/ProductWindow";
import { RunFundDialog } from "./Landing/RunFundDialog";

const NUMBERS = [
  { value: 3000, label: "startups a seed fund sees each year", gold: false },
  { value: 10, label: "it actually backs", gold: true },
  { value: 2, label: "analysts to read them all", gold: false },
];

const navLink =
  "text-[14px] tracking-[0.2px] whitespace-nowrap text-muted transition-colors hover:text-ink focus-visible:text-ink";

/** Painted botanical band behind the product window, with a slow 0.15× parallax. */
function PaintedBand({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion();
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, (v) => (reduce ? 0 : v * 0.15));
  const image = "bg-[url('/botanical-band.png')] bg-cover bg-center bg-no-repeat";
  return (
    <section
      id="how-it-works"
      aria-label="A full Bellwether run"
      className="relative flex w-full flex-auto scroll-mt-[24px] flex-col items-center overflow-hidden pt-[40px] pb-[40px] md:min-h-0 md:flex-[1_1_0px] md:pt-[72px] md:pb-0"
    >
      {/* The image drifts down slower than the page; a mirrored copy above it fills the gap it leaves. */}
      <motion.div aria-hidden className="pointer-events-none absolute inset-0" style={{ y }}>
        <div className={`absolute inset-0 ${image}`} />
        <div className={`absolute inset-x-0 bottom-full h-full -scale-y-100 ${image}`} />
      </motion.div>
      {children}
    </section>
  );
}

/** "/": the brief landing page (design/screens/1-landing.png). Renders outside the app shell. */
export default function Landing() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // "/?start" opens the URL box straight away (handy deep link for the demo).
  const [runOpen, setRunOpen] = useState(() => params.has("start"));
  const { data: fund } = useApi(() => getFund(), []);
  const bandRef = useRef<HTMLDivElement>(null);
  const openRun = useCallback(() => setRunOpen(true), []);
  const closeRun = useCallback(() => setRunOpen(false), []);

  const scrollToRun = (e: MouseEvent) => {
    e.preventDefault();
    bandRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex w-full md:min-h-[1520px] min-w-0 flex-col overflow-x-clip bg-bg text-ink">
        {/* Nav */}
        <header className="flex w-full shrink-0 items-center justify-between gap-[16px] p-[18px_16px] md:p-[18px_56px]">
          <Link to="/" className="flex shrink-0 items-center gap-[7px] text-ink no-underline md:w-[220px]" aria-label="Bellwether home">
            <Sprout size={20} aria-hidden />
            <span className="text-[22px] tracking-[-0.4px] whitespace-nowrap">Bellwether</span>
          </Link>
          <nav className="hidden items-center gap-[36px] md:flex" aria-label="Main">
            <a href="#how-it-works" onClick={scrollToRun} className={navLink}>
              How it works
            </a>
            <Link to="/universe" className={navLink}>
              Trust
            </Link>
            <a href="#how-it-works" onClick={scrollToRun} className={navLink}>
              FAQ
            </a>
          </nav>
          <div className="flex shrink-0 items-center justify-end gap-[8px] md:w-[220px]">
            <Link
              to="/deals"
              className="rounded-[11px] p-[9px_12px] text-[14px] max-sm:hidden tracking-[0.2px] whitespace-nowrap text-ink transition-opacity hover:opacity-70"
            >
              Sign in
            </Link>
            <Pill size="md" onClick={openRun}>
              Try Bellwether
            </Pill>
          </div>
        </header>

        {/* Hero */}
        <main className="flex w-full shrink-0 flex-col items-start gap-[22px] p-[64px_16px_56px] md:p-[64px_56px_56px]">
          <Headline />
          <motion.p
            {...fadeUp(FADE_START)}
            className="m-0 text-[30px] tracking-[-0.4px] text-predicted md:whitespace-nowrap"
          >
            Great deals get missed because nobody had time to look.
          </motion.p>
          <motion.p
            {...fadeUp(FADE_START + FADE_STEP)}
            className="m-0 text-[21px]/[30px] tracking-[0.2px] text-muted md:whitespace-nowrap"
          >
            Bellwether gives every VC fund a team of AI analysts. Paste the fund’s website:
            <br className="hidden md:inline" /> they learn what it invests in, find its next deals and write the diligence, every
            day.
          </motion.p>
          <motion.dl
            {...fadeUp(FADE_START + FADE_STEP * 2)}
            className="m-0 flex flex-wrap gap-x-[56px] gap-y-[16px] p-[8px_0]"
          >
            {NUMBERS.map((n, i) => (
              <div key={n.label} className="flex flex-col-reverse gap-[4px]">
                <dt className="text-[15px] tracking-[0.2px] whitespace-nowrap text-muted">{n.label}</dt>
                <dd className={`m-0 text-[44px] tracking-[-0.8px] whitespace-nowrap ${n.gold ? "text-predicted" : "text-ink"}`}>
                  <CountUp value={n.value} delay={FADE_START + FADE_STEP * 2 + 0.15 + i * 0.1} />
                </dd>
              </div>
            ))}
          </motion.dl>
          <motion.div {...fadeUp(FADE_START + FADE_STEP * 3)} className="flex flex-wrap items-center gap-[12px] pt-[10px]">
            <Pill arrow onClick={openRun}>
              Run Bellwether on a fund
            </Pill>
            <Pill tone="sage" onClick={() => navigate(`/research?run=${encodeURIComponent(DEMO_RUN_ID)}&fund=localglobe`)}>
              Watch a recorded run
            </Pill>
          </motion.div>
        </main>

        {/* Painted band + product window */}
        <div ref={bandRef} className="flex w-full flex-auto flex-col md:min-h-0 md:flex-[1_1_0px]">
          <PaintedBand>
            <ProductWindow dna={fund?.fund.dna} onReadMemo={() => navigate("/memos?fund=accel")} />
          </PaintedBand>
        </div>

        <RunFundDialog open={runOpen} onClose={closeRun} />
      </div>
    </MotionConfig>
  );
}
