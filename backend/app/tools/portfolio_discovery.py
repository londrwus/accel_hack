"""Find a VC fund's whole portfolio from its website, fast and without a model.

    companies = await discover("https://www.indexventures.com")   # [{name, website, fund_page_url, ...}]
    result = await discover_full(url, cache=PageCache(run_id))     # + warnings, sources, parked flag

Most fund sites only show part of their portfolio in the page HTML (a "Load more" button, client-side
filters, infinite scroll). The full list usually sits somewhere a plain HTTP client can read. We try, and
merge, in this order:

1. sitemap.xml and its child sitemaps: every /companies/<slug> or /portfolio/<slug> page.
2. The CMS behind the site: Sanity's public query API, WordPress (wp-json post types, FacetWP taxonomy
   archives /<taxonomy>/<term>/page/N/), Webflow pagination (?xxxx_page=N), rel=next, and data embedded in
   Next.js pages (__NEXT_DATA__ / RSC payload).
3. Pagination until a page is empty or missing.
4. The repeated-card rule: the most common repeated block on the portfolio page that has a short name and
   one link (the company's website or its page on the fund site).

Pages are fetched with async httpx (16 at a time, 12 s each, polite user agent, robots.txt respected).
Pages can be cached per run in SQLite (`PageCache`) so a resumed run doesn't fetch them again.
Nothing here calls a model: the Reader sends only what's left to the cheap model.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from . import web

CONCURRENCY = 16
PAGE_TIMEOUT_S = 12.0
MAX_PAGE_BYTES = 6_000_000
MAX_PAGINATION = 60
MAX_SITEMAP_FILES = 12
DETAIL_FETCH_LIMIT = 120  # company pages read to find a website when the listing has none
DETAIL_MAX_BYTES = 600_000

PORTFOLIO_WORDS = re.compile(r"compan|portfolio|investment|startups|founders|backed", re.I)
_SKIP_SLUGS = {"all", "page", "exits", "exited", "active", "featured", "search", "current", "alumni", "feed",
               "category", "tag", "filter", "index", "companies", "portfolio", "investments", "live", "past"}
_SOCIAL = ("linkedin.", "twitter.", "x.com", "facebook.", "instagram.", "youtube.", "crunchbase.", "medium.com",
           "github.com", "tiktok.", "apple.com", "google.com", "goo.gl", "bit.ly", "wikipedia.", "vimeo.",
           "spotify.", "angel.co", "wellfound.", "glassdoor.", "pitchbook.", "techcrunch.", "bloomberg.",
           "ft.com", "wsj.com", "forbes.", "sifted.", "cdn.", "w3.org", "schema.org", "gstatic.", "sanity.io",
           "webflow.", "website-files.com", "wp.com", "gravatar.", "typekit.", "fonts.", "cloudflare",
           "jsdelivr", "unpkg", "hubspot", "calendly", "mailchimp", "substack.com", "storyblok.")
_PARKED = re.compile(r"domain (?:name )?(?:is |may be )?for sale|buy this domain|make an offer|this domain is parked|"
                     r"parked (?:free|domain)|domain parking|sedo\b|dan\.com|afternic|hugedomains|"
                     r"inquire about this domain", re.I)
_EXIT = re.compile(r"\b(acquired|exited|ipo|nasdaq|nyse|public|exit)\b", re.I)
_YEAR = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
_TICKER = re.compile(r"\s+(?:NASDAQ|NYSE|AMS|LSE|EPA|ETR|TSE|ASX|HKEX|SIX|BME|NSE)\s*:\s*[A-Z0-9.]+\s*$")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Discovery:
    fund_url: str
    final_url: str = ""
    companies: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # how the list was found ("sitemap", "sanity", ...)
    listing_urls: list[str] = field(default_factory=list)
    parked: bool = False
    partial: bool = False  # cut off by a timeout: companies are what was found until then
    pages_fetched: int = 0
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "Discovery":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def norm(name: str) -> str:
    """'Abacus.ai' -> 'abacusai'. The dedupe key."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def name_from_slug(slug: str) -> str:
    """'atlantic-money' -> 'Atlantic Money'; 'fireworks-ai-2' -> 'Fireworks AI'."""
    s = re.sub(r"[-_](?:\d{1,2}|[a-f0-9]{6,})$", "", slug.strip("/").split("/")[-1])
    words = [w for w in re.split(r"[-_+\s]+", s) if w]
    out = []
    for w in words:
        if w.lower() in ("ai", "io", "hq", "vr", "ar", "ml", "3d", "uk", "us", "eu"):
            out.append(w.upper())
        elif any(ch.isdigit() for ch in w):
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)[:80]


def clean_name(text: str) -> str:
    t = unescape(re.sub(r"\s+", " ", text or "")).strip(" \t-–|:•·")
    t = _TICKER.sub("", t)
    t = re.sub(r"(?i)^(link to|visit|go to)\s+", "", t)
    t = re.sub(r"(?i)['’]s website$|\s+website$|\s+logo$|^logo\s+(of\s+)?", "", t).strip()
    return t[:80]


def _good_name(t: str) -> bool:
    if not t or len(t) > 60 or len(t) < 2:
        return False
    if len(t.split()) > 6 or _YEAR.fullmatch(t) or t.isdigit():
        return False
    return t.lower() not in {"read more", "learn more", "view", "website", "visit", "more", "visit website",
                             "view company", "case study", "see more", "load more", "next", "previous"}


def _outbound(url: str, site_host: str) -> bool:
    h = web.host_of(url)
    if not h or not url.startswith("http"):
        return False
    base = site_host.split(".")[-2] if site_host.count(".") >= 1 else site_host
    if h == site_host or h.endswith("." + site_host) or (base and h.split(".")[-2:-1] == [base]):
        return False
    return not any(s in h or s in url for s in _SOCIAL)


def is_parked(html: str, text_len: Optional[int] = None) -> bool:
    """A domain-for-sale page rather than a fund site."""
    head = html[:200_000]
    return bool(_PARKED.search(head)) and (text_len is None or text_len < 4000)


# ---------------------------------------------------------------------------
# Fetching (async, bounded, robots-aware, cached per run)
# ---------------------------------------------------------------------------


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    body: str


class PageCache:
    """Raw pages for one run in SQLite, so a resumed run skips pages it already read."""

    SQL = ("CREATE TABLE IF NOT EXISTS page_cache (run_id TEXT NOT NULL, url TEXT NOT NULL, final_url TEXT, "
           "status INTEGER, body TEXT, PRIMARY KEY (run_id, url))")

    def __init__(self, run_id: str):
        self.run_id = run_id
        from .. import store  # local import: the tool works without the app (tests, scripts)
        self._store = store
        with store._lock, store.connect() as c:
            c.execute(self.SQL)

    def get(self, url: str) -> Optional[Fetched]:
        with self._store.connect() as c:
            row = c.execute("SELECT final_url, status, body FROM page_cache WHERE run_id=? AND url=?",
                            (self.run_id, url)).fetchone()
        return Fetched(url, row[0], row[1], row[2] or "") if row else None

    def put(self, f: Fetched) -> None:
        with self._store._lock, self._store.connect() as c:
            c.execute("INSERT OR REPLACE INTO page_cache (run_id, url, final_url, status, body) VALUES (?,?,?,?,?)",
                      (self.run_id, f.url, f.final_url, f.status, f.body[:MAX_PAGE_BYTES]))

    def count(self) -> int:
        with self._store.connect() as c:
            return c.execute("SELECT COUNT(*) FROM page_cache WHERE run_id=?", (self.run_id,)).fetchone()[0]


class Fetcher:
    def __init__(self, cache: Optional[PageCache] = None, *, offline: bool = False,
                 transport: Optional[httpx.AsyncBaseTransport] = None, check_public: bool = True):
        self.cache = cache
        self.offline = offline  # only cached pages (a run out of resumes)
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.client = httpx.AsyncClient(
            headers={"User-Agent": web.USER_AGENT, "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.5",
                     "Accept-Language": "en-GB,en;q=0.8"},
            follow_redirects=True, max_redirects=5, transport=transport, timeout=PAGE_TIMEOUT_S,
            verify=web.tls.context())
        self.check_public = check_public
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._public: dict[str, bool] = {}
        self._mem: dict[str, Optional[Fetched]] = {}
        self.count = 0

    async def close(self) -> None:
        await self.client.aclose()

    async def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if self.check_public and origin not in self._public:
            try:
                await web.ensure_public(origin)
                self._public[origin] = True
            except Exception:
                self._public[origin] = False
        if self.check_public and not self._public.get(origin):
            return False
        if origin not in self._robots:
            parser = None
            try:
                r = await self.client.get(origin + "/robots.txt", timeout=5)
                if r.status_code == 200 and len(r.content) < 500_000:
                    parser = RobotFileParser()
                    parser.parse(r.text.splitlines())
            except Exception:
                parser = None
            self._robots[origin] = parser
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(web.USER_AGENT, url)

    async def robots_sitemaps(self, origin: str) -> list[str]:
        if self.offline:
            return []
        await self._allowed(origin + "/")
        rp = self._robots.get(origin)
        try:
            return list(rp.site_maps() or []) if rp else []
        except Exception:
            return []

    async def get(self, url: str, *, max_bytes: int = MAX_PAGE_BYTES, robots: bool = True) -> Optional[Fetched]:
        """The page, or None (missing, blocked, not allowed, timed out)."""
        url = url.split("#")[0]
        if url in self._mem:
            return self._mem[url]
        if self.cache is not None:
            hit = await asyncio.to_thread(self.cache.get, url)
            if hit is not None:
                self._mem[url] = hit if hit.status < 400 else None
                return self._mem[url]
        if self.offline:
            return None
        out: Optional[Fetched] = None
        async with self.sem:
            try:
                if robots and not await self._allowed(url):
                    self._mem[url] = None
                    return None
                self.count += 1
                async with self.client.stream("GET", url) as r:
                    chunks, size = [], 0
                    async for ch in r.aiter_bytes():
                        chunks.append(ch)
                        size += len(ch)
                        if size >= max_bytes:
                            break
                    body = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
                    out = Fetched(url, str(r.url), r.status_code, body)
            except (httpx.HTTPError, OSError, ValueError):
                out = None  # timeouts and resets are not cached: a resume tries again
        if out is not None and self.cache is not None:
            await asyncio.to_thread(self.cache.put, out)
        if out is not None and out.status >= 400:
            out_ok = None
        else:
            out_ok = out
        self._mem[url] = out_ok
        return out_ok


# ---------------------------------------------------------------------------
# A small DOM, enough for the repeated-card rule
# ---------------------------------------------------------------------------

_VOID = {"br", "img", "input", "meta", "link", "hr", "wbr", "source", "area", "base", "col", "embed", "param", "track"}
_DROP = {"script", "style", "noscript", "svg", "template", "head"}


class Node:
    __slots__ = ("tag", "attrs", "children", "text", "parent")

    def __init__(self, tag: str, attrs: dict, parent: Optional["Node"]):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[Node] = []
        self.text: list[str] = []

    @property
    def cls(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def all_text(self) -> str:
        parts: list[str] = []

        def rec(n: Node) -> None:
            parts.extend(n.text)
            for c in n.children:
                rec(c)
        rec(self)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in _DROP:
                self.skip += 1
            return
        if tag in _DROP:
            self.skip = 1
            return
        n = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag not in _DROP:
            self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if self.skip:
            if tag in _DROP:
                self.skip -= 1
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent  # tolerate unclosed tags
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.cur.text.append(data)


def parse_html(html: str) -> Node:
    t = _Tree()
    try:
        t.feed(html)
        t.close()
    except Exception:
        pass
    return t.root


def _card_record(n: Node, base_url: str, site_host: str, detail_prefixes: set[str]) -> Optional[dict]:
    outs, details, name = [], [], ""
    alt = ""
    for d in n.walk():
        if d.tag == "a" and d.attrs.get("href"):
            href = urljoin(base_url, d.attrs["href"].strip())
            if _outbound(href, site_host):
                outs.append(href)
            elif web.host_of(href) == site_host or web.host_of(href).endswith("." + site_host):
                seg = urlparse(href).path.rstrip("/").split("/")
                if len(seg) >= 3 and seg[-1] and seg[-1].lower() not in _SKIP_SLUGS and (
                        not detail_prefixes or "/".join(seg[:-1]).lower() in detail_prefixes
                        or PORTFOLIO_WORDS.search("/".join(seg[:-1]))):
                    details.append(href.split("?")[0])
        if d.tag == "img" and not alt:
            alt = clean_name(d.attrs.get("alt", ""))
    for d in n.walk():  # an element named like a name or title
        c = " ".join(d.cls).lower()
        if d is not n and re.search(r"name|title|heading", c) and not re.search(r"sub|desc|tag", c):
            t = clean_name(d.all_text())
            if _good_name(t):
                name = t
                break
    if not name:
        for d in n.walk():
            if d.tag in ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"):
                t = clean_name(d.all_text())
                if _good_name(t):
                    name = t
                    break
    if not name and _good_name(alt):
        name = alt
    if not name:
        for d in n.walk():
            if d.tag == "a":
                t = clean_name(d.all_text())
                if _good_name(t):
                    name = t
                    break
    if not name and details:
        name = name_from_slug(details[0])
    if not name or not (outs or details):
        return None
    if len({web.host_of(u) for u in outs}) > 2:
        return None  # a container of several companies, not one card
    text = n.all_text()
    rec: dict[str, Any] = {"name": name, "website": outs[0] if outs else None,
                           "fund_page_url": details[0] if details else None}
    y = _YEAR.findall(text)
    if y:
        rec["year"] = y[0]
    if _EXIT.search(text) or any("exit" in c.lower() or "acquired" in c.lower() for c in n.cls):
        rec["status"] = "exited"
    return rec


def repeated_cards(html: str, base_url: str, detail_prefixes: Optional[set[str]] = None) -> list[dict]:
    """Companies from the most common repeated block with a name and one link."""
    root = parse_html(html)
    site_host = web.host_of(base_url)
    groups: dict[tuple, list[Node]] = defaultdict(list)
    for n in root.walk():
        if n.tag in ("root", "html", "body", "a", "img", "span", "i", "p", "h1", "h2", "h3", "h4", "h5", "h6"):
            continue
        cls = n.cls
        key = (n.parent.tag if n.parent else "", n.tag, cls[0] if cls else "", n.attrs.get("role", ""))
        groups[key].append(n)
    best: list[dict] = []
    best_score = 0.0
    for key, nodes in groups.items():
        if len(nodes) < 6:
            continue
        recs = [r for r in (_card_record(x, base_url, site_host, detail_prefixes or set()) for x in nodes) if r]
        if len(recs) < 6:
            continue
        names = {norm(r["name"]) for r in recs}
        distinct = len(names) / len(recs)
        if distinct < 0.6:
            continue
        score = len(names) * (len(recs) / len(nodes)) * distinct
        if score > best_score:
            best_score, best = score, recs
    seen: set[str] = set()
    out = []
    for r in best:
        k = norm(r["name"])
        if k and k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def detail_slug(url: str) -> Optional[tuple[str, str]]:
    """('/companies', 'figma') for a company page URL under a portfolio-like path, else None."""
    path = urlparse(url).path.rstrip("/")
    head, _, slug = path.rpartition("/")
    if not slug or "." in slug or slug.lower() in _SKIP_SLUGS:
        return None
    last = head.rsplit("/", 1)[-1]
    if not last or not PORTFOLIO_WORDS.search(last) or re.search(r"news|blog|post|categor|tag|team", head, re.I):
        return None
    return head.lower(), slug


async def from_sitemaps(f: Fetcher, origin: str) -> list[str]:
    queue = await f.robots_sitemaps(origin) or []
    for extra in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml"):
        if origin + extra not in queue:
            queue.append(origin + extra)
    seen: set[str] = set()
    urls: list[str] = []
    files = 0
    while queue and files < MAX_SITEMAP_FILES:
        batch = []
        while queue and len(batch) < 6:
            u = queue.pop(0)
            if u not in seen and web.same_site(u, origin):
                seen.add(u)
                batch.append(u)
        files += len(batch)
        for r in await asyncio.gather(*(f.get(u, max_bytes=20_000_000) for u in batch)):
            if r is None:
                continue
            locs = [unescape(x) for x in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\s\]]+)", r.body)]
            if "<sitemapindex" in r.body[:3000]:
                good = [u for u in locs if PORTFOLIO_WORDS.search(u.rsplit("/", 1)[-1])]
                rest = [u for u in locs if u not in good and re.search(r"page|post|sitemap\.xml|sitemap-0", u)]
                queue[:0] = good + rest[:3] if good else locs[:8]
            else:
                urls.extend(locs)
    return urls


def records_from_details(urls: list[str]) -> tuple[list[dict], set[str]]:
    """One record per company page; the most common company-page prefix wins (with any close ones)."""
    by_prefix: dict[str, dict[str, str]] = defaultdict(dict)
    for u in urls:
        ds = detail_slug(u)
        if ds:
            by_prefix[ds[0]].setdefault(ds[1].lower(), u.split("?")[0])
    if not by_prefix:
        return [], set()
    top = max(len(v) for v in by_prefix.values())
    keep = {p for p, v in by_prefix.items() if len(v) >= max(5, top * 0.2)}
    out, seen = [], set()
    for p in keep:
        for slug, u in by_prefix[p].items():
            if slug not in seen:
                seen.add(slug)
                out.append({"name": name_from_slug(slug), "fund_page_url": u, "slug": slug, "_from_slug": True})
    return out, keep


async def from_sanity(f: Fetcher, html: str) -> list[dict]:
    m = re.findall(r"cdn\.sanity\.io/(?:images|files)/([a-z0-9]{6,12})/([a-z0-9_-]+)/", html)
    m += re.findall(r'projectId["\']?\s*[:=]\s*["\']([a-z0-9]{8})["\'][^}]{0,200}?dataset["\']?\s*[:=]\s*["\']([a-z0-9_-]+)', html)
    if not m:
        return []
    project, dataset = Counter(m).most_common(1)[0][0]
    api = f"https://{project}.apicdn.sanity.io/v2021-10-21/data/query/{dataset}"

    async def q(query: str) -> Any:
        r = await f.get(api + "?" + urlencode({"query": query}), robots=False, max_bytes=30_000_000)
        try:
            return json.loads(r.body)["result"] if r else None
        except Exception:
            return None

    types = await q("array::unique(*[]._type)") or []
    cands = [t for t in types if isinstance(t, str) and re.fullmatch(
        r"(?i)(portfolio)?(company|companies|portfolioCompany|portfolioItem|investment|startup|portfolio)", t)]
    out: list[dict] = []
    for t in cands[:2]:
        rows = await q(f'*[_type=="{t}" && !(_id in path("drafts.**"))]'
                       '{"name": coalesce(name, title, companyName), "website": coalesce(website, websiteUrl, url, link),'
                       ' "slug": slug.current, "year": coalesce(firstInvestDate, year, investmentYear),'
                       ' "exited": coalesce(exited, isExited, acquired), "archived": archived}') or []
        for r in rows:
            if not isinstance(r, dict) or not isinstance(r.get("name"), str) or r.get("archived") is True:
                continue
            rec = {"name": clean_name(r["name"]), "website": r.get("website") if isinstance(r.get("website"), str) else None,
                   "slug": r.get("slug") if isinstance(r.get("slug"), str) else None}
            if r.get("year"):
                rec["year"] = str(r["year"])[:4]
            if r.get("exited") is True:
                rec["status"] = "exited"
            if rec["name"]:
                out.append(rec)
        if out:
            break
    return out


async def from_wp_json(f: Fetcher, origin: str) -> list[dict]:
    r = await f.get(origin + "/wp-json/wp/v2/types")
    try:
        types = json.loads(r.body) if r else {}
    except Exception:
        return []
    if not isinstance(types, dict):
        return []
    bases = [v.get("rest_base") for k, v in types.items() if isinstance(v, dict) and v.get("rest_base")
             and re.search(r"compan|portfolio|investment|startup", k + " " + str(v.get("rest_base")), re.I)]
    out: list[dict] = []
    for base in bases[:2]:
        for page in range(1, 21):
            r = await f.get(f"{origin}/wp-json/wp/v2/{base}?per_page=100&page={page}&_fields=title,link,slug,acf")
            try:
                rows = json.loads(r.body) if r else []
            except Exception:
                rows = []
            if not isinstance(rows, list) or not rows:
                break
            for x in rows:
                name = clean_name(re.sub(r"<[^>]+>", "", ((x.get("title") or {}).get("rendered") or "")))
                if not name:
                    continue
                acf = x.get("acf") if isinstance(x.get("acf"), dict) else {}
                site = next((v for k, v in acf.items() if isinstance(v, str) and "web" in k.lower()
                             and v.startswith("http")), None)
                out.append({"name": name, "fund_page_url": x.get("link"), "slug": x.get("slug"), "website": site})
            if len(rows) < 100:
                break
    return out


def facet_archives(html: str, origin: str) -> list[str]:
    """FacetWP (WordPress) facets -> taxonomy archive URLs such as /status/live/ that list every company."""
    m = re.search(r"FWP_JSON\s*=\s*(\{.*?\});\s*\n", html, re.S)
    if not m:
        return []
    try:
        facets = json.loads(m.group(1)).get("preload_data", {}).get("facets", {})
    except Exception:
        return []
    out = []
    for name, markup in facets.items():
        if not isinstance(markup, str) or "pager" in name:
            continue
        values = re.findall(r'(?:data-value|value)="([a-z0-9][a-z0-9-]*)"', markup)
        tax = name.split("_", 1)[1] if "_" in name else name
        for v in dict.fromkeys(values):
            out.append(f"{origin}/{tax}/{v}/")
    return out


async def paginate(f: Fetcher, first_url: str, first_html: str,
                   extract: Callable[[str, str], list[dict]]) -> list[dict]:
    """Follow Webflow ?xxxx_page=N, rel=next and /page/N/ links until a page is empty or missing."""
    found: list[dict] = []
    seen_keys: set[str] = set()
    wf = re.search(r"[?&]([a-f0-9]{4,12}_page)=\d+", first_html)
    if wf:
        param = wf.group(1)
        base = first_url.split("?")[0]
        n = 2
        while n <= MAX_PAGINATION:
            pages = await asyncio.gather(*(f.get(f"{base}?{param}={k}") for k in range(n, n + 4)))
            stop = False
            for r in pages:
                recs = extract(r.body, r.final_url) if r else []
                new = [x for x in recs if norm(x["name"]) not in seen_keys]
                if not new:
                    stop = True
                    break
                for x in new:
                    seen_keys.add(norm(x["name"]))
                found += new
                if f"{param}=" not in r.body:
                    stop = True
                    break
            if stop:
                break
            n += 4
        return found
    url, html = first_url, first_html
    for _ in range(MAX_PAGINATION):
        nxt = re.search(r'<link[^>]+rel=["\']next["\'][^>]*href=["\']([^"\']+)', html) or \
            re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']next["\']', html) or \
            re.search(r'<a[^>]+rel=["\']next["\'][^>]*href=["\']([^"\']+)', html) or \
            re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']next["\']', html)
        if not nxt:
            m = re.search(r"/page/(\d+)/?$", urlparse(url).path)
            cur = int(m.group(1)) if m else 1
            cand = re.search(rf'href=["\']([^"\']*/page/{cur + 1}/?)["\']', html)
            nxt = cand
        if not nxt:
            break
        nu = urljoin(url, unescape(nxt.group(1)))
        if nu == url:
            break
        r = await f.get(nu)
        if r is None:
            break
        recs = extract(r.body, r.final_url)
        new = [x for x in recs if norm(x["name"]) not in seen_keys]
        if not new:
            break
        for x in new:
            seen_keys.add(norm(x["name"]))
        found += new
        url, html = r.final_url, r.body
    return found


def _listing_links(html: str, base_url: str) -> list[str]:
    host = web.host_of(base_url)
    out = []
    for href in re.findall(r'<a\b[^>]*href=["\']([^"\'#]+)', html, re.I):
        u = urljoin(base_url, unescape(href)).split("#")[0]
        if web.host_of(u) != host:
            continue
        path = urlparse(u).path.rstrip("/")
        segs = [s for s in path.split("/") if s]
        if 1 <= len(segs) <= 2 and PORTFOLIO_WORDS.search(segs[-1]) and not re.search(
                r"news|blog|post|press|jobs|career", path, re.I):
            out.append(u.split("?")[0])
    ranked = sorted(dict.fromkeys(out), key=lambda u: (len(urlparse(u).path), u))
    return ranked[:3]


def _detail_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(url, anchor text) for company pages linked from a listing page."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        u = urljoin(base_url, unescape(m.group(1))).split("?")[0]
        if web.same_site(u, base_url) and detail_slug(u):
            txt = clean_name(re.sub(r"<[^>]+>", " ", m.group(2)))
            out.append((u, txt))
    return out


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


class Merger:
    def __init__(self, site_host: str):
        self.site_host = site_host
        self.by_key: dict[str, dict] = {}
        self.slug_key: dict[str, str] = {}
        self.site_key: dict[str, str] = {}

    def add(self, rec: dict, source: str) -> None:
        name = clean_name(rec.get("name") or "")
        if not _good_name(name):
            return
        slug = (rec.get("slug") or (detail_slug(rec["fund_page_url"]) or (None, None))[1]
                if rec.get("fund_page_url") else rec.get("slug"))
        slug = slug.lower() if isinstance(slug, str) else None
        site = rec.get("website")
        if site and not _outbound(site if site.startswith("http") else "https://" + site, self.site_host):
            site = None
        dom = web.host_of(site if site and site.startswith("http") else f"https://{site}") if site else None
        key = (self.slug_key.get(slug) if slug else None) or (self.site_key.get(dom) if dom else None) \
            or (norm(name) if norm(name) in self.by_key else None)
        if key is None:
            key = norm(name)
            if not key:
                return
            self.by_key[key] = {"name": name, "website": None, "fund_page_url": None, "sector": None,
                                "year": None, "status": None, "found_by": source, "_from_slug": True}
        cur = self.by_key[key]
        if cur.get("_from_slug") and not rec.get("_from_slug"):
            cur["name"] = name  # a real name beats one made from a slug
            cur["_from_slug"] = False
        for k in ("fund_page_url", "sector", "year", "status"):
            if rec.get(k) and not cur.get(k):
                cur[k] = rec[k]
        if site and not cur.get("website"):
            cur["website"] = site if site.startswith("http") else "https://" + site
        if slug:
            self.slug_key.setdefault(slug, key)
        if dom:
            self.site_key.setdefault(dom, key)

    def companies(self) -> list[dict]:
        out = []
        for c in self.by_key.values():
            d = {k: v for k, v in c.items() if not k.startswith("_")}
            out.append(d)
        return out


def _website_from_detail(html: str, url: str, slug: str, site_host: str) -> Optional[str]:
    toks = [t for t in re.split(r"[-_]", slug.lower()) if len(t) >= 3]
    cands = []
    for m in re.finditer(r'<a\b[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        u = unescape(m.group(1))
        if not _outbound(u, site_host):
            continue
        h = web.host_of(u)
        txt = re.sub(r"<[^>]+>", " ", m.group(2)).lower()
        score = (2 if any(t in h.replace(".", "").replace("-", "") for t in toks) else 0) + \
            (1 if re.search(r"website|visit|\.com|\.io|\.ai", txt) else 0)
        if score:
            cands.append((score, u))
    return max(cands)[1] if cands else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def discover_full(fund_url: str, *, cache: Optional[PageCache] = None, offline: bool = False,
                        transport: Optional[httpx.AsyncBaseTransport] = None, check_public: bool = True,
                        detail_limit: int = DETAIL_FETCH_LIMIT, log: Optional[Callable[[str], None]] = None,
                        into: Optional[Discovery] = None) -> Discovery:
    """Pass `into` to keep partial results: if the call is cancelled (e.g. by asyncio.wait_for timing out),
    `into.companies` still holds everything merged so far and `into.partial` is True."""
    t0 = time.monotonic()
    say = log or (lambda _m: None)
    url = web.normalize_url(fund_url)
    res = into if into is not None else Discovery(fund_url=url)
    res.fund_url = url
    f = Fetcher(cache, offline=offline, transport=transport, check_public=check_public)
    merger: Optional[Merger] = None
    slug_recs: list[dict] = []
    sitemap: list[str] = []
    try:
        home = await f.get(url)
        if home is None and not offline:
            alt = re.sub(r"://www\.", "://", url) if "://www." in url else url.replace("://", "://www.", 1)
            home = await f.get(alt)
        if home is None:
            res.warnings.append("couldn't open the website")
            return res
        res.final_url = home.final_url
        if is_parked(home.body, len(re.sub(r"<[^>]+>", " ", home.body))):
            res.parked = True
            res.warnings.append(f"{web.host_of(home.final_url)} looks like a parked domain (for sale), not the fund's site")
            return res
        p = urlparse(home.final_url)
        origin = f"{p.scheme}://{p.netloc}"
        site_host = web.host_of(origin)
        merger = Merger(site_host)

        listing_urls = _listing_links(home.body, home.final_url)
        if not listing_urls:
            listing_urls = [origin + "/portfolio", origin + "/companies"]
        sitemap_task = asyncio.create_task(from_sitemaps(f, origin))
        wp_task = asyncio.create_task(from_wp_json(f, origin)) if "wp-content" in home.body else None
        listings = [r for r in await asyncio.gather(*(f.get(u) for u in listing_urls)) if r is not None]
        res.listing_urls = [r.final_url for r in listings]

        # Company pages the site lists: sitemap + links on the listing pages
        sitemap = await sitemap_task
        link_recs = []
        for r in listings:
            for u, txt in _detail_links(r.body, r.final_url):
                link_recs.append((u, txt))
        slug_recs, prefixes = records_from_details(sitemap + [u for u, _ in link_recs])
        anchors = {u.split("?")[0]: t for u, t in link_recs if _good_name(t)}
        if slug_recs:
            in_map = sum(1 for r in slug_recs if r["fund_page_url"] in set(sitemap))
            if in_map:
                res.sources.append(f"sitemap ({in_map})")

        # The CMS behind the site
        cms_html = "\n".join([home.body[:3_000_000]] + [r.body[:3_000_000] for r in listings])
        sanity = await from_sanity(f, cms_html)
        if sanity:
            res.sources.append(f"sanity ({len(sanity)})")
            for r in sanity:
                merger.add(r, "sanity")
        if wp_task is not None:
            wp = await wp_task
            if wp:
                res.sources.append(f"wp-json ({len(wp)})")
                for r in wp:
                    merger.add(r, "wp-json")

        def cards(html: str, base: str) -> list[dict]:
            return repeated_cards(html, base, prefixes)

        for r in listings:
            got = cards(r.body, r.final_url)
            if got:
                res.sources.append(f"cards on {urlparse(r.final_url).path or '/'} ({len(got)})")
            for x in got:
                merger.add(x, "cards")
            more = await paginate(f, r.final_url, r.body, cards)
            if more:
                res.sources.append(f"pagination ({len(more)})")
            for x in more:
                merger.add(x, "pagination")
            try:  # Next.js / JSON-LD data embedded in the page
                emb, _facets = web.embedded_records(r.body, r.final_url)
            except Exception:
                emb = []
            emb = [e for e in emb if e.get("website") or (e.get("slug") and any(
                s["slug"] == e["slug"] for s in slug_recs))]
            if emb:
                res.sources.append(f"embedded data ({len(emb)})")
            for e in emb:
                merger.add({"name": e.get("name"), "website": e.get("website"), "slug": e.get("slug"),
                            "status": "exited" if e.get("exited") else None}, "embedded")
            archives = facet_archives(r.body, origin)
            if archives:
                got_arch: list[dict] = []

                async def crawl(a: str) -> list[dict]:
                    first = await f.get(a)
                    if first is None:
                        return []
                    first_recs = _archive_records(first.body, first.final_url, prefixes)
                    return first_recs + await paginate(
                        f, first.final_url, first.body, lambda h, b: _archive_records(h, b, prefixes))
                for chunk in await asyncio.gather(*(crawl(a) for a in archives[:40])):
                    got_arch += chunk
                if got_arch:
                    res.sources.append(f"taxonomy archives ({len({norm(x['name']) for x in got_arch})})")
                for x in got_arch:
                    merger.add(x, "archives")

        for rec in slug_recs:  # last: names from slugs only fill gaps
            u = rec["fund_page_url"]
            if u in anchors:
                rec = {**rec, "name": anchors[u], "_from_slug": False}
            merger.add(rec, "sitemap" if u in set(sitemap) else "links")

        companies = merger.companies()
        # Websites from company pages, where cheap
        need = [c for c in companies if not c["website"] and c["fund_page_url"]]
        if need and detail_limit and not offline:
            todo = need[:detail_limit]
            pages = await asyncio.gather(*(f.get(c["fund_page_url"], max_bytes=DETAIL_MAX_BYTES) for c in todo))
            got = 0
            for c, r in zip(todo, pages):
                if r is None:
                    continue
                slug = (detail_slug(c["fund_page_url"]) or ("", ""))[1]
                w = _website_from_detail(r.body, r.final_url, slug or c["name"], site_host)
                if w:
                    c["website"] = w
                    got += 1
            if got:
                res.sources.append(f"company pages ({got} websites)")
        res.companies = companies
        if len(companies) < 10:
            res.warnings.append("found very few portfolio companies; the list may load in a way we can't read")
        m = re.search(r"([1-9]\d{1,3})\s*\+?\s*(?:companies|startups|investments|founders)",
                      re.sub(r"<[^>]+>", " ", home.body), re.I)
        if m and len(companies) < int(m.group(1)) * 0.5:
            res.warnings.append(f"the site mentions {m.group(1)} companies but only {len(companies)} were found")
        say(f"discovered {len(companies)} companies via {', '.join(res.sources) or 'nothing'}")
        return res
    except asyncio.CancelledError:
        if merger is not None and not res.companies:
            in_map = set(sitemap)
            for rec in slug_recs:  # company pages already found but not merged yet
                merger.add(rec, "sitemap" if rec["fund_page_url"] in in_map else "links")
            res.companies = merger.companies()
            res.partial = True
            res.warnings.append(f"portfolio search ran out of time; kept the {len(res.companies)} companies found so far")
        raise
    finally:
        res.pages_fetched = f.count
        res.seconds = round(time.monotonic() - t0, 1)
        await f.close()


def _archive_records(html: str, base: str, prefixes: set[str]) -> list[dict]:
    """Company links on a taxonomy archive page (name + profile URL)."""
    recs, seen = [], set()
    for u, txt in _detail_links(html, base):
        ds = detail_slug(u)
        if not ds or ds[1] in seen:
            continue
        seen.add(ds[1])
        recs.append({"name": txt if _good_name(txt) else name_from_slug(ds[1]), "fund_page_url": u, "slug": ds[1],
                     "_from_slug": not _good_name(txt)})
    if "/status/" in base:
        seg = urlparse(base).path.split("/")
        st = seg[seg.index("status") + 1] if "status" in seg and seg.index("status") + 1 < len(seg) else None
        for r in recs:
            r["status"] = "exited" if st and "exit" in st else (st or None)
    return recs


async def discover(fund_url: str, **kw: Any) -> list[dict]:
    """[{name, website, fund_page_url, sector, year, status}] for every portfolio company we can find."""
    return (await discover_full(fund_url, **kw)).companies


__all__ = ["discover", "discover_full", "Discovery", "PageCache", "repeated_cards", "name_from_slug",
           "is_parked", "norm", "facet_archives"]
