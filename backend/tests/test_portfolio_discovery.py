"""Portfolio discovery on small saved pages (no network: httpx.MockTransport)."""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app import store
from app.tools import portfolio_discovery as pd

FIX = Path(__file__).parent / "fixtures" / "discovery"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _transport(routes: dict[str, str], *, robots: str = "", hits: list[str] | None = None,
               sanity: dict | None = None) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if hits is not None:
            hits.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots)
        if sanity is not None and "api.sanity.io" in url or "apicdn.sanity.io" in url:
            q = parse_qs(urlparse(url).query)["query"][0]
            body = sanity["types"] if "array::unique" in q else sanity["rows"]
            return httpx.Response(200, json={"result": body})
        key = url.split("#")[0]
        if key in routes:
            body = routes[key]
            ctype = "application/xml" if body.lstrip().startswith("<?xml") else "text/html"
            return httpx.Response(200, text=body, headers={"content-type": ctype})
        return httpx.Response(404, text="not found")
    return httpx.MockTransport(handler)


def _run(url: str, transport: httpx.MockTransport, **kw) -> pd.Discovery:
    return asyncio.run(pd.discover_full(url, transport=transport, check_public=False, detail_limit=0, **kw))


def test_name_from_slug_and_clean():
    assert pd.name_from_slug("atlantic-money") == "Atlantic Money"
    assert pd.name_from_slug("fireworks-ai") == "Fireworks AI"
    assert pd.name_from_slug("1stdibs") == "1stdibs"
    assert pd.clean_name("Link to Waniwani&#039;s website") == "Waniwani"
    assert pd.clean_name("Adyen AMS:ADYEN") == "Adyen"


def test_repeated_cards_seedcamp_style():
    recs = pd.repeated_cards(_read("cards.html"), "https://fund.test/our-companies/")
    names = [r["name"] for r in recs]
    assert names[:3] == ["Waniwani", "Eversettled", "Atlas Robotics"]
    assert len(recs) == 9
    assert recs[0]["website"] == "https://waniwani.com"
    assert recs[0]["year"] == "2010"
    assert "LinkedIn" not in names and "Twitter" not in names


def test_parked_domain():
    assert pd.is_parked(_read("parked.html"), 200)
    assert not pd.is_parked(_read("home.html"), 100)
    res = _run("https://point9.test/", _transport({"https://point9.test/": _read("parked.html")}))
    assert res.parked and res.companies == []
    assert "parked" in res.warnings[0]


def test_webflow_pagination_and_sitemap_merge():
    routes = {
        "https://fund.test/": _read("home.html"),
        "https://fund.test/companies": _read("webflow_p1.html"),
        "https://fund.test/companies?a1b2c3d4_page=2": _read("webflow_p2.html"),
        "https://fund.test/companies?a1b2c3d4_page=3": _read("webflow_p3.html"),
        "https://fund.test/sitemap.xml": _read("sitemap_index.xml"),
        "https://fund.test/sitemap-companies.xml": _read("sitemap_companies.xml"),
    }
    res = _run("https://fund.test/", _transport(routes))
    names = {c["name"] for c in res.companies}
    assert {f"Alpha{i}" for i in range(8)} <= names
    assert {f"Beta{i}" for i in range(8)} <= names
    assert {"Atlantic Money", "Fireworks AI", "Zeta Labs"} <= names  # only in the sitemap
    assert "Alpha0" in names and sum(1 for c in res.companies if pd.norm(c["name"]) == "alpha0") == 1
    alpha = next(c for c in res.companies if c["name"] == "Alpha0")
    assert alpha["website"] == "https://alpha0.io" and alpha["fund_page_url"].endswith("/companies/alpha0")
    assert any(s.startswith("pagination") for s in res.sources)


def test_robots_disallow_is_respected():
    hits: list[str] = []
    routes = {"https://fund.test/": _read("home.html"), "https://fund.test/companies": _read("webflow_p1.html")}
    res = _run("https://fund.test/", _transport(routes, robots="User-agent: *\nDisallow: /companies", hits=hits))
    assert not any(u.startswith("https://fund.test/companies") for u in hits)
    assert res.companies == []


def test_facetwp_taxonomy_archives():
    routes = {
        "https://fund.test/": '<html><body><a href="/companies/">Companies</a><img src="/wp-content/x.png"></body></html>',
        "https://fund.test/companies/": _read("facetwp.html"),
        "https://fund.test/status/live/": _read("archive_live_1.html"),
        "https://fund.test/status/live/page/2/": _read("archive_live_2.html"),
        "https://fund.test/status/exited/": _read("archive_exited_1.html"),
    }
    res = _run("https://fund.test/", _transport(routes))
    by = {c["name"]: c for c in res.companies}
    assert set(by) == {"Lovable", "Revolut", "Wayflyer", "Darktrace"}
    assert by["Darktrace"]["status"] == "exited"
    assert by["Lovable"]["fund_page_url"] == "https://fund.test/company/lovable/"


def test_sanity_public_api():
    routes = {
        "https://fund.test/": '<html><body><img src="https://cdn.sanity.io/images/abcd1234/production/x.png">'
                              '<a href="/companies">Companies</a></body></html>',
        "https://fund.test/companies": "<html><body>loading</body></html>",
    }
    sanity = {"types": ["page", "company", "companyCards"],
              "rows": [{"name": "Remora", "website": "https://remoracarbon.com/", "slug": "remora"},
                       {"name": "Ownwell", "website": "https://www.ownwell.com/", "slug": "ownwell"},
                       {"name": "Old Co", "archived": True}]}
    res = _run("https://fund.test/", _transport(routes, sanity=sanity))
    assert {c["name"] for c in res.companies} == {"Remora", "Ownwell"}
    assert res.sources and res.sources[0].startswith("sanity")


def test_page_cache_makes_resume_skip_fetches():
    store.init_db()
    routes = {"https://fund.test/": _read("home.html"), "https://fund.test/companies": _read("cards.html")}
    cache = pd.PageCache("run-cache-test")
    first: list[str] = []
    a = _run("https://fund.test/", _transport(routes, hits=first), cache=cache)
    assert len(a.companies) == 9 and cache.count() >= 2
    second: list[str] = []
    b = _run("https://fund.test/", _transport(routes, hits=second), cache=cache, offline=True)
    assert second == []  # everything came from SQLite
    assert json.dumps(sorted(c["name"] for c in b.companies)) == json.dumps(sorted(c["name"] for c in a.companies))


def test_timeout_keeps_partial_results():
    routes = {
        "https://fund.test/": _read("home.html"),
        "https://fund.test/companies": _read("webflow_p1.html"),
        "https://fund.test/sitemap.xml": _read("sitemap_index.xml"),
        "https://fund.test/sitemap-companies.xml": _read("sitemap_companies.xml"),
    }
    sync = _transport(routes)

    async def handler(req: httpx.Request) -> httpx.Response:
        if "_page=" in str(req.url):  # pagination hangs: the deadline hits mid-crawl
            await asyncio.sleep(30)
        return sync.handle_request(req)

    async def go() -> pd.Discovery:
        res = pd.Discovery(fund_url="https://fund.test/")
        try:
            await asyncio.wait_for(pd.discover_full("https://fund.test/", transport=httpx.MockTransport(handler),
                                                    check_public=False, detail_limit=0, into=res), timeout=1.0)
        except asyncio.TimeoutError:
            pass
        return res

    res = asyncio.run(go())
    names = {c["name"] for c in res.companies}
    assert res.partial
    assert {f"Alpha{i}" for i in range(8)} <= names  # from the first listing page
    assert {"Atlantic Money", "Zeta Labs"} <= names  # from the sitemap, merged on timeout
    assert any("ran out of time" in w for w in res.warnings)
