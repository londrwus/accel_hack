# Design

Source of truth for the frontend. Designs live in **pen.dev**: `C:\Users\Lenovo\Documents\accel.pen`.

## Direction

A light-theme take on **lightfern.com**: calm, editorial and warm. It avoids "AI dashboard" clichés: no gradients, no glowing
purple, no icon in every box. The page should feel like a well-made product sitting on top of a vintage botanical painting.

- Big, **light-weight** headlines (weight 350), lots of air.
- **Pill** buttons. The primary is gold with a light-tint circle holding an ink arrow. The secondary is sage.
- Product shown inside **windows** (hairline border, soft long shadow, a fake address-bar pill) that bleed off the
  bottom of a full-width painted band.
- Quiet **"Label: value"** pairs with a subtle filled chip for the value (like Lightfern's `To: [laura@…]`).
- Icons are rare, thin (lucide, 1.5px) and small. They never replace words.
- **No black/dark fills and no boxed cards inside the platform.** Group content with whitespace and hairline dividers. The only surface is the one main "window" per screen. Dark ink is for text and thin icons only.

`accel.pen` also contains a frame `REF · lightfern.com (reference only)`: an import of their site for reference.
Don't ship anything from it (copy, logos, artwork). Our botanical images are generated.

## Tokens

| Token | Value | Use |
|---|---|---|
| `bg` | `#F1EEE8` | page (warm paper) |
| `surface` | `#FAF8F4` | windows, panels |
| `ink` | `#1A1817` | text and thin icons only. Never a fill |
| `muted` / `subtle` | `#6B675F` / `#9A958B` | secondary text / labels |
| `border` | `#E0DBD1` (panels use `#1A181714`) | hairlines |
| `chip` | `#1A18170D` | filled chips, secondary buttons, active tab |
| `cta` | `#D8B56A` | primary button (Lightfern gold, `oklch(.79 .1 84)`) |
| `sage` | `#A3BBA6` | secondary button, section label pills |
| `accent` / `accent-soft` | `#5C7A63` / `#E2EAE1` | **portfolio** nodes, success, "working" status |
| `predicted` / `predicted-soft` | `#B8892E` / `#F4E9CF` | **Bellwether's picks**: nodes, fit scores, highlights |
| `competitor` | `#BDB7AC` | competitor nodes |
| `warning` / `warning-soft` | `#A85A2A` / `#F5E6DA` | recovered events, unverified claims |
| `danger` | `#B4432A` | conflict edges / flags |

**Type:** `Hanken Grotesk` (closest Google font to Lightfern's Season Sans). Display 80–96px at weight 350 and letter-spacing
-1.2; section headings 20–26px at 350; body 14–15px at 400 with +0.2 tracking. Mono: `JetBrains Mono` for times, scores and URLs.
**Radius:** pills 999 · windows/panels 16 · chips 999. **Shadow:** windows `0 30 80 #1A181740`; buttons `0 2 5 rgba(50,50,105,.15)`.

**Color meaning is fixed across every screen:** sage = the fund already owns it · gold = Bellwether's pick · grey = competitor ·
terracotta = clash/warning. The legend on the map says this in words.

## Screens (landing + 6 platform pages)

Naming rule: use **finance/VC words**, never AI-product words. Say *Deal Flow, Portfolio, Market Map, Investment Memos, Research,
analyst team*. Never say "Mission Control", "agents dashboard" or "AI memos". The agents appear as the **analyst team**.

| # | Frame in accel.pen | Route | Question it answers | Primary action |
|---|---|---|---|---|
| 1 | `1 · Landing (Start)` | `/` | "What problem does this solve?" | Run Bellwether on a fund |
| 2 | `2 · Deal Flow` | `/deals` | "Which startups should we look at next, and why now?" | Open a company / Add company |
| 3 | `3 · Portfolio` | `/portfolio` | "What's happening with the companies we already own?" | Weekly LP report |
| 4 | `4 · Research` | `/research` | "What is the analyst team doing right now?" | Run again |
| 5 | `5 · Market Map` | `/map` | "Where do our companies, their rivals and our next deals sit?" | Read memo |
| 6 | `6 · Investment Memo` | `/memos/:id` | "Should we meet this company, and can we trust this?" | Move to first meeting / Pass |
| 7 | `7 · Startup Universe` | `/universe` | "What data is behind this, and does the model actually work?" | Retrain model / Download CSV |
| 8 | (built in code, no frame) | `/companies/:id` | "What is this company, and how did it score for this fund?" | Read memo / Visit website |

Company page (`/companies/:id`): reached by clicking any company or signal (Deal Flow rows, Portfolio tiles, Market Map
nodes, Universe rows, memo header, company names in the Research feed). Sections: header (logo, name, one-liner, chips,
website, *Read memo*), About, Score breakdown (big fit number, a bar per part incl. *Fits the thesis (judge)*, what pushed it
up or down, closest portfolio companies, what the model weighs most), Signals (each with its source), Funding & investors
(display only, never used for scoring), Market, Companies like this, Data sources. API: `GET /api/companies/{id}/detail`.

Demo order: Landing → Research (run starts live) → Deal Flow → Market Map → Investment Memo → Portfolio → Startup Universe (proof).

### 2 · Deal Flow
A ranked table of the next deals. Toolbar: segmented *All 61 / New 3 / Under review 12 / Passed 46*, plus Sector filter and "Best fit first" sort.
Columns: **Company** (initial tile, name, one-liner) · Sector · Stage · **Fit** (% + mini bar, gold ≥80) · **Signals** (chips with icon: gold =
timing, e.g. *Raising now*; sage = strength, e.g. *Revenue up 3×*, *Like BioOrbit*; grey = info, e.g. *In Sifted this week*; terracotta = risk,
e.g. *Competes with Cleo*) · Seen · Status chip (New / Under review / Passed; passed rows faded). The footer notes that only public data is used.

### 3 · Portfolio
Deliberately **not a table**, so it looks different from Deal Flow. A KPI strip without boxes (hairline dividers): 42 companies backed · £38M invested ·
**5 likely to raise soon** (gold) · **3 need attention** (terracotta) · 14 new signals this week. Below it is a **board** of 4 columns, grouped by
what the partner should do: **Needs attention** (terracotta) → **Likely to raise soon** (gold, plan the follow-on) → **Doing well** (sage)
→ **Exited** (faded). Each column has a coloured dot, title, count chip and a one-line explanation. Each company is a light tile (initial, name,
one-liner, stage chip), its newest signals as icon rows, and "Updated 2d ago". Long columns end in "+ N more". Every signal links to its source.
Placeholder data: real portfolio names get only neutral or positive signals. Negative examples use made-up companies (e.g. "Harbor Labs").

### 7 · Startup Universe (the proof page)
Shows judges that the data and model are real. Header: green status "Model trained on Modal · 2h ago", Download CSV, gold **Retrain model**.
KPI strip: 10,412 startups · 38 sectors · 64 countries · **16 of 20** past LocalGlobe deals found by the model (gold) · 3.2s to score all.
Left: a searchable **data table** of the CSV (row ID `#4821` in mono, company + one-liner, sector, country, stage, founded, fit % for the fund)
with Sector/Country/Stage/Founded filters. The footer says "Source: data/companies.csv · every memo claim links back to a row ID".
Right rail (no boxes): **Backtest** ("we hid LocalGlobe's last 20 deals…": Bellwether model vs keyword search vs random pick, as bars) ·
**What the score depends on** (segmented bar + legend of the model's feature weights) · **Model card** (trained on Modal, data size, method,
retrains nightly, plus "Never used: gender, age, ethnicity" chips struck through).
**All numbers here must come from a real backtest run before the demo.** The design numbers are placeholders. Never show invented accuracy.

### 1 · Landing (one page, very brief)
Nav → big headline **"The first systematic VC operating system."** (96px) → the problem line in gold ("Great deals get missed because nobody had time to look.") → sub → three numbers
(3,000 seen · **10** backed · 2 analysts) → CTAs → **one big product window** on a painted band showing a full run:
agent lines streaming, Fund DNA, and the #1 pick card. Nothing else: no feature sections and no footer clutter.
The URL input lives behind "Run Bellwether on a fund" (a modal or inline input), with example funds LocalGlobe / Haatch / Seedcamp.

### App shell (platform pages 2–7)
The landing is Lightfern-style marketing. The **platform** uses a calm SaaS shell (references: a Linear/Attio-like sidebar and an
"Operator" assistant panel):
- Background `shell #EFEDE8`. The **sidebar** (264px) sits directly on it, and the **main panel** is a white (`panel`) rounded-16 surface
  with a `hair #E7E3DC` border and 8px inset.
- **Sidebar** (component `Sidebar` in the `Components` frame): workspace header (sage glossy tile + fund name + collapse icon) ·
  grey **search** field with a `/` key hint · group *Fund* (Deal Flow + glossy count badge, Portfolio, Market Map, Investment Memos, Research) and
  *Funds you cover* (funds, + Add a fund) · a **watch card** (soft mesh-gradient art, floating icon, gold "Run now", progress ring "4 of 7",
  "Details") · Trust & safety · Help · profile row.
- **Active nav item** = white pill + hairline + 1px shadow. Inactive items are muted text with a thin 18px icon.
- **Page header** inside the main panel: title 22px (+ breadcrumb or subtitle) on the left; status chip + white secondary + gold primary on the right.

### Components (`Components` frame in accel.pen)
| Component | Spec |
|---|---|
| `Button/Gold` (primary) | radius 12, gradient `#E6C886→#D3AD5E`, 1px `#B8923F` border, inner top highlight `#FFFFFF80`, soft gold drop shadow. Optional leading icon. |
| `Button/White` (secondary) | white, 1px hairline, 1px shadow, muted icon |
| `Button/Ghost` | text only, muted ("Skip") |
| `Nav/Item` | 18px icon + 15px label, optional glossy sage count badge |
| Segmented control | grey track `#1A18170A`, active segment = white pill with shadow |
| Data card | hairline card: header label + ⋯ · **segmented bar** · legend rows (dot · label · value · (%)) · footer action + `+ Save` |
No black buttons or fills. The references used near-black glossy buttons; we use the same glossy treatment in gold or white.

### 4 · Research
Header (status chip "Working · 2m 14s", Share, **Run again**) → **agent strip**: 8 agent chips (initial avatar, ✓ done, gold dot = working,
faded = waiting) → body: **Live activity** feed (time · agent · plain-English message · tag chip: *New match*, *Recovered*, *Hand-off*,
*Plan*) on the left. On the right is the **Partner panel**, modelled on the Operator reference: header (✳ Partner, settings, close), the user's request
bubble (light, not dark), a collapsible **Thought process · 7 steps** checklist, a plain-English answer, a **data card** "What LocalGlobe invests in"
(segmented sector bar + legend + Save), a "Since yesterday" gold note, and an "Ask Partner anything…" input with a gold send button.

### 5 · Market Map
Header with a segmented filter (All / Owned / Competitors / Picks), Export and **Read memo**. Dominant: the node map (React Flow).
The fund sits at the centre in pale sage, sage portfolio nodes surround it, small grey competitors sit on the outside, and gold **pick** nodes carry a fit % pill.
A red edge marks a clash with a portfolio company, and the legend is in words. Right panel (360): **Next deals**, with #1 expanded showing *why* (3 plain bullets),
fit bars and the gold "Read the diligence memo" button, then #2–#3. A conflict flag sits on Ledgerly, and the shortlist-mix chip is at the bottom.

### 6 · Investment Memo
Header with a breadcrumb (Investment Memos › Northbeam Health), Share and Export PDF. Centre: the memo column (760px, centred) with a title + fit chip
and meta chips, then *Why it fits*, *Risks* and *Questions for the founder*. Every claim has a source chip, and unverified claims are terracotta.
Right rail (340): **Your decision** (gold "Move to first meeting", white Pass / Dig deeper) and **Can you trust this memo?** (Critic
results, conflicts, "never used to score" chips struck through, and the disclaimer).

## Company logos

Real companies show their **real logo** (Portfolio tiles, Market Map portfolio and competitor nodes, the sidebar fund tile). The backend
resolves it (`backend/app/tools/logos.py`): the dataset logo (`/api/logos/dataset/<file>`), else the icon from the company's own website,
fetched once in the background and cached in `data/cache/logos/` (`/api/logos/site/<file>`), else the Google favicon for its domain, else
an initial tile. `CompanyLogo` turns `/api/...` paths into absolute URLs on the API host.
Made-up demo companies (Northbeam Health, Ledgerly, Harbor Labs…) keep initial tiles. Never invent a logo. Design assets live in
`C:\Users\Lenovo\Documents\logos\` next to `accel.pen`.

## Motion (copy Lightfern's feel)

Use `motion` (Framer Motion). Easing `[0.22, 1, 0.36, 1]`. Everything respects `prefers-reduced-motion`.

| Where | Animation |
|---|---|
| Hero headline | **Per-letter rise**: each character sits in an overflow-clipped span and slides up from 100%, staggered 15ms, 600ms per letter. Lightfern's h1 is built exactly this way. |
| Sub, numbers, CTAs | Fade-up (y 12 → 0, opacity 0 → 1), staggered after the headline. Numbers **count up**. |
| Painted band | Slow parallax on the image (0.15× scroll). The window rises 60px into place when it scrolls into view. |
| Product window / live feed | New agent lines slide in from 8px with a fade. The current agent name has a soft shimmer while working. Text in the #1 pick card types in. |
| Buttons | Hover opacity .9, press .95. The arrow circle nudges 2px right on hover. |
| Tabs | The active pill background slides between tabs (shared layout animation). |
| Market Map | Nodes scale in from the fund outward (portfolio → competitors → picks). Gold pick nodes have a slow 2s glow pulse. Edges draw in. |
| Memo | Sections fade in as the Analyst finishes them. Critic badges pop in one by one. |

## shadcn/ui mapping

Button (custom `pill` variants: `gold`, `sage`, `chip`, `ink`), Badge (chip), Card (panel), Tabs (pill), Progress, Tooltip,
ScrollArea (feed), Sheet (mobile panels), Dialog (URL input). Map: `@xyflow/react` with custom node components.
