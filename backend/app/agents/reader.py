"""Reader: reads the fund's website (home, portfolio, team, blog) and lists the portfolio.

Fallbacks, in order: the website -> web search results -> the dataset's investor index.
Model: the extract model (MODEL_EXTRACT; cheap extraction from page text).
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from pydantic import BaseModel, Field

from ..models import Company, Source
from .. import store
from ..tools import dataset, portfolio_discovery, web
from .context import RunContext, StageFailed, plan
from .llm import EXTRACT_MODEL, WORKER_MODEL, LLMError, LLMUnavailable, dumps

# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


class ExtractedCompany(BaseModel):
    name: str
    website: Optional[str] = None
    one_liner: Optional[str] = None
    sector: Optional[str] = None
    exited: bool = False


class ExtractedPerson(BaseModel):
    name: str
    role: str


class ReaderExtract(BaseModel):
    """What the extract model pulls out of the fund's pages."""

    fund_name: str
    portfolio: list[ExtractedCompany]
    team: list[ExtractedPerson]
    blog_topics: list[str]
    stated_focus: str
    stage_hint: Optional[str] = None
    cheque_hint: Optional[str] = None
    geo_hint: Optional[str] = None


class PortfolioCompany(BaseModel):
    company: Company
    exited: bool = False
    in_dataset: bool = False


class ReaderResult(BaseModel):
    fund_name: str
    fund_url: str
    pages_read: list[Source] = Field(default_factory=list)
    portfolio: list[PortfolioCompany] = Field(default_factory=list)
    team: list[ExtractedPerson] = Field(default_factory=list)
    blog_topics: list[str] = Field(default_factory=list)
    stated_focus: str = ""
    stage_hint: Optional[str] = None
    cheque_hint: Optional[str] = None
    geo_hint: Optional[str] = None
    used_fallback: Optional[str] = None


SYSTEM = (
    "You are Reader, part of Bellwether, a research assistant for a venture capital fund. You read a fund's "
    "public website and pull out facts. " + web.UNTRUSTED_RULES + " Only list companies the pages say the "
    "fund invested in. List people only by public name and role; never guess anyone's gender, age, "
    "ethnicity or nationality. If something isn't on the pages, leave it empty rather than guessing. "
    "Write short plain English."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class PortfolioOnly(BaseModel):
    portfolio: list[ExtractedCompany]


class SectorLabel(BaseModel):
    i: int
    sector: str


class SectorLabels(BaseModel):
    labels: list[SectorLabel]


SECTORS = ("B2B SaaS", "Consumer", "Healthcare", "AI", "Fintech", "Marketplace", "Edtech", "Deep tech", "Proptech",
           "Gaming", "Dev tools", "Cybersecurity", "Climate", "Biotech", "Logistics", "Energy", "Hardware",
           "Mobility", "Web3", "Robotics", "Insurtech", "Semiconductors", "Defense")
LABEL_CHUNK = 100  # small chunks run in parallel: ~15 s for 800 companies


DISCOVERY_TIMEOUT_S = 180  # 7 runs in parallel slowed discovery past 90 s (Balderton, Index)
MAX_PORTFOLIO = 1500  # big funds (Accel lists ~800) are kept whole; prompts only see a sample
PORTFOLIO_PAGE_BYTES = 8_000_000  # JS-rendered portfolio pages carry their data inline and can be large
CHUNK_CHARS = 14_000
MAX_CHUNKS = 4


def _match_row(name: str, domain: Optional[str], known: set[str]) -> Optional[dict]:
    """The dataset row for a portfolio company, or None. Careful with names alone: "Billy" or "Nova" are
    shared by many startups, so a name-only match needs the dataset to agree the fund backed it, or a
    distinctive name, and must not contradict the website the fund lists."""
    if domain:
        row = dataset.find(domain=domain)
        if row:
            return row
    row = dataset.find(name=name)
    if not row:
        return None
    row_dom = (row.get("domain") or "").lower().removeprefix("www.")
    if domain and row_dom and row_dom != domain:
        return None
    if row["id"] in known or domain:
        return row
    return row if len(dataset._norm_name(name).replace(" ", "")) >= 7 else None


def _company_from_extract(e: ExtractedCompany, known: Optional[set[str]] = None) -> PortfolioCompany:
    domain = web.host_of(e.website) if e.website else None
    if domain and domain.split(".")[0] in ("linkedin", "twitter", "x", "facebook", "crunchbase", "instagram"):
        domain = None
    row = _match_row(e.name, domain, known or set())
    if row:
        c = dataset.company(row)
        if domain and not c.website:  # keep the website the fund lists (needed for the logo)
            c.website = domain
            c.logo = c.logo or f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        if not c.one_liner and e.one_liner:
            c.one_liner = e.one_liner[:200]
        return PortfolioCompany(company=c, exited=e.exited, in_dataset=True)
    slug = dataset._norm_name(e.name).replace(" ", "-") or "company"
    if dataset.get(slug):  # a different company in the dataset already uses this id ("bird" is not Bird)
        slug = f"{slug}-portfolio"
    return PortfolioCompany(
        company=Company(id=slug, row_id=None, name=e.name.strip()[:80], one_liner=(e.one_liner or "")[:200],
                        sector=(e.sector or "Other")[:40], stage="Acquired" if e.exited else "Unknown",
                        country=None, city=None, founded=None, website=domain,
                        logo=f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None),
        exited=e.exited, in_dataset=False)


def _merge_dataset_portfolio(ctx: RunContext, result: ReaderResult) -> int:
    """Add companies the dataset says the fund backed. Returns how many were new."""
    have = {p.company.id for p in result.portfolio} | {p.company.name.lower() for p in result.portfolio}
    added = 0
    for row in dataset.fund_portfolio(ctx.fund_id, result.fund_name):
        if row["id"] in have or row["name"].lower() in have:
            continue
        result.portfolio.append(PortfolioCompany(company=dataset.company(row), in_dataset=True))
        added += 1
    return added


def _name_from_slug(slug: str) -> str:
    words = re.sub(r"-\d+$", "", slug).replace("-", " ").replace("_", " ").split()
    return " ".join(w if any(ch.isdigit() for ch in w) else w.capitalize() for w in words)[:80]


def _structured_portfolio(pages: list[web.Page], slugs: dict[str, str],
                          anchors: dict[str, str]) -> list[ExtractedCompany]:
    """Portfolio companies from data the site embeds in its pages, plus every /companies/<slug> page it lists.

    No model is needed for this part, so it scales to hundreds of companies at no cost.
    """
    recs: dict[str, dict] = {}
    for p in pages:
        for r in p.records:
            key = r.get("slug") or r["name"].lower()
            if slugs:
                ok = r.get("slug") in slugs or (not r.get("slug") and r.get("website"))
            else:
                ok = bool(r.get("website"))
            if ok and key not in recs:
                recs[key] = r
    out: list[ExtractedCompany] = []
    for r in recs.values():
        desc = r.get("description") or None
        if desc and web.suspicious_lines(desc):
            desc = None
        out.append(ExtractedCompany(name=r["name"], website=r.get("website"), one_liner=desc,
                                    exited=bool(r.get("exited"))))
    have = {r.get("slug") for r in recs.values()}
    for slug in slugs:
        if slug not in have:
            name = anchors.get(slug) or _name_from_slug(slug)
            out.append(ExtractedCompany(name=name))
    return out


async def _label_sectors(ctx: RunContext, portfolio: list[PortfolioCompany]) -> int:
    """Give a sector to portfolio companies the site lists without one (cheap model, in parallel chunks).

    Big portfolios are often just names and logos. Without sectors, Thesis can't say what the fund backs.
    Returns how many got a label.
    """
    todo = [p for p in portfolio if p.company.sector in ("", "Other") and not p.in_dataset]
    if len(todo) < 5:
        return 0
    allowed = {x.lower(): x for x in SECTORS}
    chunks = [todo[i:i + LABEL_CHUNK] for i in range(0, len(todo), LABEL_CHUNK)][:8]

    async def one(chunk: list[PortfolioCompany]) -> int:
        items = [{"i": i, "name": p.company.name, "website": p.company.website, "what": p.company.one_liner[:100]}
                 for i, p in enumerate(chunk)]
        out = await ctx.llm.json(
            model=EXTRACT_MODEL, effort="low", system=SYSTEM, schema=SectorLabels,
            prompt=("These are portfolio companies listed on a venture fund's website. Give each one sector from "
                    f"this list: {', '.join(SECTORS)}. Use the description when there is one, otherwise what is "
                    "generally known about the company. If you don't recognise a company and there is no "
                    "description, use \"Unknown\". Return one label per i.\n\n" + dumps(items)),
            on_retry=ctx.retry_hook("Reader", "sorting the portfolio by sector"))
        n = 0
        for lab in out.labels:
            sec = allowed.get(lab.sector.strip().lower())
            if sec and 0 <= lab.i < len(chunk):
                chunk[lab.i].company.sector = sec
                n += 1
        return n

    outs = await asyncio.gather(*(one(c) for c in chunks), return_exceptions=True)
    for o in outs:
        if isinstance(o, LLMUnavailable):
            raise o
    return sum(o for o in outs if isinstance(o, int))


def _chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    out, cur = [], []
    n = 0
    for line in text.splitlines():
        if n + len(line) > size and cur:
            out.append(chr(10).join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur:
        out.append(chr(10).join(cur))
    return out


def source_label(url: str) -> str:
    """localglobe.vc/portfolio"""
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    return (web.host_of(url) + path)[:60]


def _span(names: list[str]) -> str:
    if not names:
        return ""
    s = sorted(names, key=str.lower)
    return f", from {s[0]} to {s[-1]}" if len(s) > 2 else f": {' and '.join(s)}"


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


async def run(ctx: RunContext) -> ReaderResult:
    emit = ctx.emit
    host = web.host_of(ctx.url) or ctx.url
    emit.handoff("Partner", "Reader", f"Asked Reader to read {host}.", f"Fund website: {host}",
                 **plan("read", "working"))

    pages: list[web.Page] = []
    portfolio_pages: list[web.Page] = []
    failed_url: str | None = None
    sitemap_task = asyncio.create_task(_sitemap(ctx.url))
    discovery_task = asyncio.create_task(_discover(ctx))  # the full portfolio list, no model needed
    home = await ctx.fetch("Reader", ctx.url, host)
    if home is not None:
        pages.append(home)
        picked = web.find_links(home, limit=5)
        kinds = sorted({k for k, _ in picked})
        emit.step("Reader", "Read the home page." + (f" Found pages about the {', '.join(kinds)}." if kinds else ""))
        for kind, link in picked:
            label = {"portfolio": "the portfolio page", "team": "the team page", "blog": "the blog",
                     "thesis": "the page about how they invest"}.get(kind, "a page")
            page = await ctx.fetch("Reader", link.url, label,
                                   max_bytes=PORTFOLIO_PAGE_BYTES if kind == "portfolio" else web.MAX_BYTES)
            if page is not None:
                pages.append(page)
                if kind == "portfolio":
                    portfolio_pages.append(page)
            elif kind == "portfolio" and failed_url is None:
                failed_url = link.url

    # Every company page the site lists: from links on the portfolio pages and from sitemap.xml. JS-heavy
    # sites only show part of the list in the page itself (Accel: about 200 of 780).
    sitemap = await sitemap_task
    listing = portfolio_pages[0].final_url if portfolio_pages else ctx.url
    anchors: dict[str, str] = {}
    link_urls: list[str] = []
    for p in portfolio_pages:
        for lk in p.links:
            link_urls.append(lk.url)
            slug = web.detail_slugs([lk.url], listing)
            if slug and lk.text and 1 < len(lk.text) <= 60:
                anchors.setdefault(next(iter(slug)), lk.text)
    slugs = web.detail_slugs(link_urls + sitemap, listing)
    if sitemap:
        in_map = len(web.detail_slugs(sitemap, listing))
        emit.tool("Reader", "sitemap", f"Read the site map: {len(sitemap):,} pages"
                  + (f", including {in_map:,} company pages." if in_map else "."), url=ctx.url, pages=len(sitemap))
    structured = _structured_portfolio(portfolio_pages, slugs, anchors)
    structured = await _merge_discovery(ctx, structured, discovery_task)
    if structured:
        with_site = sum(1 for e in structured if e.website)
        emit.step("Reader", f"The portfolio page lists {len(structured):,} companies "
                  f"({with_site:,} with their website), read straight from the page's data.")

    result = ReaderResult(fund_name=ctx.fund_name, fund_url=ctx.url)
    result.pages_read = [Source(label=source_label(p.final_url), url=p.final_url) for p in pages]
    blocks = [web.wrap_untrusted(p.final_url, f"Title: {p.title}" + chr(10) + p.text
                                 + ((chr(10) + "Filters on this page: " + chr(10) + chr(10).join(p.facets))
                                    if p.facets else ""), limit=15_000) for p in pages]

    if not pages or failed_url:  # site or portfolio page blocked: try search results instead
        what = host if not pages else "the portfolio page"
        emit.step("Reader", f"Couldn't open {what}. Looking in search results instead.")
        try:
            found = await ctx.llm.search(
                model=WORKER_MODEL, max_uses=3, effort="low",
                system=SYSTEM, prompt=(f"Find the venture capital fund whose website is {host}. List its "
                                       "portfolio companies (with their websites), its team (names and roles "
                                       "only), what it says it invests in, typical stage, cheque size and "
                                       "geography. Cite sources."),
                on_retry=ctx.retry_hook("Reader", "searching for the fund"))
            if found.text:
                blocks.append(web.wrap_untrusted(f"search results for {host}", found.text, limit=15_000,
                                                 label="untrusted_source"))
                result.used_fallback = "search results"
                result.pages_read += [Source(label=web.host_of(h.url), url=h.url) for h in found.hits[:3]]
        except LLMUnavailable:
            raise
        except LLMError:
            pass

    known = {r["id"] for r in dataset.fund_portfolio(ctx.fund_id, ctx.fund_name)}
    have_list = len(structured) >= 10
    portfolio_ask = ("Leave the portfolio list empty: it was already read from the page's data. "
                     if have_list else
                     "Extract its portfolio companies (name, website if shown, one-line description, a short "
                     "sector label such as Fintech, Health, Climate, AI, Deep tech, Consumer, B2B SaaS; mark "
                     "exited companies). ")
    extra_chunks: list[str] = []
    if not have_list:  # a long text-only portfolio: read the rest of it in pieces with the cheap model
        for p in portfolio_pages:
            extra_chunks += [web.wrap_untrusted(p.final_url, c, limit=CHUNK_CHARS + 500)
                             for c in _chunks(p.text[15_000:])]
        extra_chunks = extra_chunks[:MAX_CHUNKS]
    if blocks:
        try:
            calls = [ctx.llm.json(
                model=EXTRACT_MODEL, effort="low", system=SYSTEM, schema=ReaderExtract,
                prompt=("Here are pages from a venture fund's website. Extract the fund's name. " + portfolio_ask
                        + "Extract the team (public name and role only; up to 40 people, partners first), blog "
                        "post topics, and what the fund says it invests in (sectors, stage, cheque size, "
                        "geography) in one or two sentences.\n\n" + "\n\n".join(blocks)),
                on_retry=ctx.retry_hook("Reader", "reading the pages"))]
            calls += [ctx.llm.json(
                model=EXTRACT_MODEL, effort="low", system=SYSTEM, schema=PortfolioOnly,
                prompt=("This is part of a venture fund's portfolio page. List every portfolio company on it "
                        "(name, website if shown, one-line description, short sector label; mark exited "
                        "companies).\n\n" + chunk),
                on_retry=ctx.retry_hook("Reader", "reading the portfolio")) for chunk in extra_chunks]
            if extra_chunks:
                emit.step("Reader", f"The portfolio page is long, so I'm reading it in {len(extra_chunks) + 1} "
                          "parts at once.")
            outs = await asyncio.gather(*calls, return_exceptions=True)
            for o in outs:
                if isinstance(o, LLMUnavailable):
                    raise o
            if isinstance(outs[0], BaseException):
                raise outs[0]
            extract = outs[0]
            result.fund_name = extract.fund_name.strip() or ctx.fund_name
            found = list(structured) + list(extract.portfolio)
            for o in outs[1:]:
                if isinstance(o, PortfolioOnly):
                    found += o.portfolio
            seen: set[str] = set()
            ids: set[str] = set()
            for e in found:
                key = dataset._norm_name(e.name) or e.name.lower()
                if e.name and key not in seen and len(result.portfolio) < MAX_PORTFOLIO:
                    seen.add(key)
                    pc = _company_from_extract(e, known)
                    if pc.company.id not in ids:  # two spellings of one company
                        ids.add(pc.company.id)
                        result.portfolio.append(pc)
            result.team = extract.team[:40]
            result.blog_topics = extract.blog_topics[:10]
            result.stated_focus = extract.stated_focus
            result.stage_hint, result.cheque_hint, result.geo_hint = (extract.stage_hint, extract.cheque_hint,
                                                                      extract.geo_hint)
        except LLMUnavailable:
            raise
        except LLMError as exc:
            emit.warning("Reader", f"Couldn't make sense of the pages ({exc}). Using the dataset instead.",
                         tag="Retrying")
            if structured and not result.portfolio:
                result.portfolio = [_company_from_extract(e, known) for e in structured[:MAX_PORTFOLIO]]
    elif structured:
        result.portfolio = [_company_from_extract(e, known) for e in structured[:MAX_PORTFOLIO]]

    ctx.fund_name = result.fund_name
    from_site = len(result.portfolio)
    added = _merge_dataset_portfolio(ctx, result)
    if added and from_site == 0:
        result.used_fallback = result.used_fallback or "dataset"
        emit.recovered("Reader", f"The website didn't list the portfolio, so I used the {added} companies "
                       "the dataset says the fund backed.", fallback="dataset")
    elif result.used_fallback == "search results":
        what = "The website" if failed_url is None else "The portfolio page"
        emit.recovered("Reader", f"{what} was blocked, so I used search results instead.",
                       fallback="search results", url=failed_url or ctx.url)

    if not result.portfolio and not result.stated_focus:
        raise StageFailed(f"Couldn't read {host} or find the fund anywhere else.")

    names = [p.company.name for p in result.portfolio]
    if names:
        emit.step("Reader", f"The portfolio lists {len(names)} companies{_span(names)}."
                  + (f" {added} more came from the dataset." if added and from_site else ""))
    matched = sum(p.in_dataset for p in result.portfolio)
    if matched:
        emit.step("Reader", f"Matched {matched:,} of them to companies in our dataset of startups.")
    if len(result.portfolio) >= 20:
        try:
            labelled = await _label_sectors(ctx, result.portfolio)
            if labelled:
                emit.step("Reader", f"Sorted {labelled:,} companies that had no sector on the site into sectors.")
        except LLMUnavailable:
            raise
        except LLMError:
            pass
    if result.team:
        emit.step("Reader", f"Found {len(result.team)} people on the team page. Only names and roles are kept.")
    emit.handoff("Reader", "Thesis", f"Found {len(names)} portfolio companies and handed them to Thesis.",
                 f"{len(names)} portfolio companies", **plan("read", "done"))
    return result


def dataset_rows(result: ReaderResult) -> list[dict]:
    """Portfolio companies that exist in the dataset (for scoring and similarity)."""
    out = []
    for p in result.portfolio:
        r = dataset.get(p.company.id) if p.in_dataset else None
        if r:
            out.append(r)
    return out


def portfolio_sample(result: ReaderResult, limit: int = 80) -> list[PortfolioCompany]:
    """Up to `limit` companies spread across the whole portfolio, described ones first."""
    pf = result.portfolio
    if len(pf) <= limit:
        return pf
    described = [p for p in pf if p.company.one_liner]
    pool = described if len(described) >= limit else described + [p for p in pf if not p.company.one_liner]
    step = len(pool) / limit if len(described) >= limit else 1
    return [pool[int(i * step)] for i in range(limit)] if step > 1 else pool[:limit]


def portfolio_brief(result: ReaderResult, limit: int = 80) -> str:
    return dumps([{"id": p.company.id, "name": p.company.name, "what": p.company.one_liner[:120],
                   "sector": p.company.sector, "exited": p.exited} for p in portfolio_sample(result, limit)])


async def _discover(ctx: RunContext) -> Optional[portfolio_discovery.Discovery]:
    """Run portfolio discovery once per run. Pages and the result are checkpointed in SQLite, so a resumed
    run doesn't fetch them again; after too many restarts only cached pages are used."""
    key = f"ckpt:{ctx.run_id}:reader:discovery"
    saved = store.get_memory(ctx.fund_id, key)
    if saved:
        try:
            return portfolio_discovery.Discovery.from_dict(saved)
        except Exception:
            pass
    res = portfolio_discovery.Discovery(fund_url=ctx.url)
    try:
        cache = portfolio_discovery.PageCache(ctx.run_id)
        await asyncio.wait_for(
            portfolio_discovery.discover_full(ctx.url, cache=cache, offline=ctx.out_of_resumes("read"), into=res),
            timeout=DISCOVERY_TIMEOUT_S)
    except asyncio.TimeoutError:  # keep what was found before the deadline
        if not res.companies:
            return None
    except Exception:  # discovery is a bonus on top of the pages the Reader reads itself
        return None
    if (res.companies and not res.partial) or res.parked:  # partial: a resume retries (pages are cached)
        store.set_memory(ctx.fund_id, key, res.to_dict())
    return res


async def _merge_discovery(ctx: RunContext, structured: list[ExtractedCompany],
                           task: "asyncio.Task") -> list[ExtractedCompany]:
    res = await task
    if res is None:
        return structured
    for w in res.warnings:
        ctx.emit.warning("Reader", w[0].upper() + w[1:] + ".")
    if not res.companies:
        return structured
    have = {dataset._norm_name(e.name) for e in structured}
    out = list(structured)
    added = 0
    for c in res.companies:
        k = dataset._norm_name(c["name"])
        if not k or k in have:
            continue
        have.add(k)
        out.append(ExtractedCompany(name=c["name"], website=c.get("website"), sector=c.get("sector"),
                                    exited=c.get("status") == "exited"))
        added += 1
    how = ", ".join(s.split(" (")[0] for s in res.sources[:4])
    ctx.emit.step("Reader", f"Found {len(res.companies):,} portfolio companies across the site"
                  + (f" ({how})" if how else "") + f" in {res.seconds:.0f} s."
                  + (f" {added:,} weren't on the portfolio page itself." if added and structured else ""))
    return out


async def _sitemap(url: str) -> list[str]:
    try:
        return await asyncio.wait_for(web.sitemap_urls(url), timeout=12)
    except Exception:  # no sitemap is normal
        return []


__all__ = ["ReaderResult", "PortfolioCompany", "run", "dataset_rows", "portfolio_brief", "source_label"]
