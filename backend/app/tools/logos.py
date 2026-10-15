"""Company logos: dataset file -> cached logo from the company's website -> None (initial tile).

`resolve()` never blocks on the network. When a logo isn't cached yet it queues a background fetch and returns the
best thing it has right now (the dataset file, the Google favicon URL for a known domain, or None); the next page
load picks up the cached file.

Served by the API as:
    /api/logos/dataset/<file>   data/raw/logos/<file>            (from the dataset's logo_file column)
    /api/logos/site/<file>      data/cache/logos/<domain>.<ext>  (fetched from the company's site)

Name-only companies (no website, not in the dataset, e.g. portfolio names read off a fund site) get a guessed
domain (name.com / .ai / .io / .co / .co.uk) that is only kept when the page title names the company.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import threading
import time
import queue
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from .. import config

log = logging.getLogger("bellwether.logos")

DATASET_LOGOS = config.DATA_DIR / "raw" / "logos"
SITE_LOGOS = config.CACHE_DIR / "logos"
_INDEX_FILE = SITE_LOGOS / "index.json"  # key -> file name ("" = tried, nothing found)
_GOOGLE = "https://www.google.com/s2/favicons?domain={}&sz=128"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Bellwether/0.1 (logo fetch)"}
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/svg+xml": "svg",
        "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico", "image/webp": "webp", "image/gif": "gif"}

_lock = threading.Lock()
_pending: set[str] = set()
_jobs: "queue.Queue[tuple]" = queue.Queue()
_workers: list[threading.Thread] = []
_WORKERS = 6


def _worker() -> None:
    while True:
        args = _jobs.get()
        try:
            _fetch_job(*args)
        finally:
            _jobs.task_done()


def _submit(*args) -> None:
    """Daemon workers, so a server reload or shutdown never waits for logo downloads."""
    if not _workers:
        with _lock:
            while len(_workers) < _WORKERS:
                t = threading.Thread(target=_worker, name=f"logo-{len(_workers)}", daemon=True)
                t.start()
                _workers.append(t)
    _jobs.put(args)
_index: Optional[dict[str, str]] = None
_last_save = 0.0


# ---------------------------------------------------------------------------
# Dataset logos
# ---------------------------------------------------------------------------


def _norm_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(inc|ltd|limited|llc|plc|gmbh|sas|bv|corp|co|the|hq)\b", " ", n)
    return " ".join(n.split())


def domain_of(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    u = website if "://" in website else "https://" + website
    host = (urlparse(u).hostname or "").lower()
    return (host[4:] if host.startswith("www.") else host) or None


@lru_cache(maxsize=1)
def _dataset() -> dict[str, dict[str, tuple[str, Optional[str]]]]:
    """slug / row id / domain / name -> (logo file or "", domain)."""
    by: dict[str, dict] = {"id": {}, "row": {}, "domain": {}, "name": {}}
    path = config.companies_csv()
    if not path.exists():
        return by
    with path.open(encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            file = (rec.get("logo_file") or "").strip()
            file = file.split("/")[-1] if file and (DATASET_LOGOS / file.split("/")[-1]).exists() else ""
            dom = domain_of(rec.get("domain") or rec.get("website"))
            val = (file, dom)
            if rec.get("id"):
                by["id"][rec["id"].strip()] = val
            if (rec.get("row_id") or "").strip().isdigit():
                by["row"][int(rec["row_id"])] = val
            if dom:
                by["domain"].setdefault(dom, val)
            nn = _norm_name(rec.get("name") or "")
            if nn:
                by["name"].setdefault(nn, val)
    return by


def _dataset_match(company_id: Optional[str], row_id: Optional[int], domain: Optional[str],
                   name: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    d = _dataset()
    if row_id is not None and row_id in d["row"]:
        return d["row"][row_id]
    if company_id and company_id in d["id"]:
        return d["id"][company_id]
    if domain and domain in d["domain"]:
        return d["domain"][domain]
    if name and _norm_name(name) in d["name"]:
        return d["name"][_norm_name(name)]
    return None


# ---------------------------------------------------------------------------
# Site logo cache
# ---------------------------------------------------------------------------


def _load_index() -> dict[str, str]:
    global _index
    if _index is None:
        try:
            _index = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            _index = {}
    return _index


def _save_index() -> None:
    try:
        SITE_LOGOS.mkdir(parents=True, exist_ok=True)
        _INDEX_FILE.write_text(json.dumps(_load_index(), indent=0), encoding="utf-8")
    except Exception:
        log.exception("could not save the logo index")


def _remember(key: str, file: str, extra: Optional[dict[str, str]] = None) -> None:
    """Record a result. Merges into the file on disk (other API processes share it) instead of overwriting."""
    global _last_save
    with _lock:
        idx = _load_index()
        idx[key] = file
        idx.update(extra or {})
        _pending.discard(key)
        # Merging and rewriting the whole file on every logo held the lock that page requests need, making
        # pages take 20s+ while a portfolio of hundreds was being fetched. Save at most every 3s, or when idle.
        if time.monotonic() - _last_save < 3 and not _jobs.empty():
            return
        _last_save = time.monotonic()
        try:
            on_disk = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
            for k, v in on_disk.items():
                idx.setdefault(k, v)
        except Exception:
            pass
        _save_index()


def _queue(key: str, domain: Optional[str], name: Optional[str], sector: Optional[str] = None) -> None:
    if key in _pending or key in _load_index():  # lock-free fast path
        return
    with _lock:
        if key in _pending or key in _load_index():
            return
        _pending.add(key)
    _submit(key, domain, name, sector)


def resolve(name: Optional[str] = None, website: Optional[str] = None, row_id: Optional[int] = None,
            company_id: Optional[str] = None, fetch: bool = True, sector: Optional[str] = None) -> Optional[str]:
    """Best logo URL right now (relative /api/logos/... or an absolute URL), or None."""
    domain = domain_of(website)
    hit = _dataset_match(company_id, row_id, domain, name)
    if hit:
        file, ds_domain = hit
        if file:
            return f"/api/logos/dataset/{file}"
        domain = domain or ds_domain
    key = domain or (f"name:{_norm_name(name or '')}" if name and _norm_name(name) else None)
    if not key:
        return None
    cached = _load_index().get(key)
    if cached:
        return f"/api/logos/site/{cached}"
    if cached is None and fetch:
        _queue(key, domain, name, sector)
    return None  # initial tile until the background fetch has saved a file (no broken-image requests)


def site_file(file: str) -> Optional[Path]:
    p = (SITE_LOGOS / file).resolve()
    return p if p.parent == SITE_LOGOS.resolve() and p.is_file() else None


def dataset_file(file: str) -> Optional[Path]:
    p = (DATASET_LOGOS / file).resolve()
    return p if p.parent == DATASET_LOGOS.resolve() and p.is_file() else None


# ---------------------------------------------------------------------------
# Fetching (background threads only)
# ---------------------------------------------------------------------------

_LINK = re.compile(r"<link\b[^>]*>", re.I)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r'([a-zA-Z:-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): unescape(m.group(3) if m.group(3) is not None else m.group(4) or "")
            for m in _ATTR.finditer(tag)}


def _candidates(html: str, base: str) -> list[str]:
    icons: list[tuple[int, str]] = []
    for tag in _LINK.findall(html):
        a = _attrs(tag)
        rel = a.get("rel", "").lower()
        href = a.get("href")
        if not href or "icon" not in rel or "mask-icon" in rel:
            continue
        size = 0
        m = re.search(r"(\d+)x\d+", a.get("sizes", ""))
        if m:
            size = int(m.group(1))
        if "apple-touch-icon" in rel:
            size = max(size, 180)
        if href.lower().endswith(".svg"):
            size = max(size, 150)
        icons.append((size, urljoin(base, href)))
    icons.sort(key=lambda t: -t[0])
    return [u for _, u in icons]


def _og_image(html: str, base: str) -> Optional[str]:
    for tag in _META.findall(html):
        a = _attrs(tag)
        if a.get("property", a.get("name", "")).lower() == "og:image" and a.get("content"):
            return urljoin(base, a["content"])
    return None


def _title(html: str) -> str:
    m = _TITLE.search(html)
    t = unescape(m.group(1)) if m else ""
    for tag in _META.findall(html):
        a = _attrs(tag)
        if a.get("property", "").lower() == "og:site_name":
            t += " " + a.get("content", "")
    return t


def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _get_image(client, url: str) -> Optional[tuple[bytes, str]]:
    try:
        r = client.get(url)
    except Exception:
        return None
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if r.status_code != 200 or len(r.content) < 120 or len(r.content) > 2_000_000:
        return None
    ext = _EXT.get(ctype)
    if not ext:
        low = url.lower().split("?")[0]
        ext = next((e for e in ("png", "jpg", "svg", "ico", "webp") if low.endswith("." + e)), None)
        if not ext or ctype.startswith("text/"):
            return None
    return r.content, ext


def _home(client, domain: str) -> Optional[tuple[str, str]]:
    for url in (f"https://{domain}", f"https://www.{domain}"):
        try:
            r = client.get(url)
        except Exception:
            continue
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            return r.text[:300_000], str(r.url)
    return None


def _guess_domains(name: str, sector: Optional[str] = None) -> list[str]:
    words = _norm_name(name).split()
    if not words:
        return []
    joined = "".join(words)
    stems = [joined]
    if len(words) > 1 and words[-1] in ("ai", "bio", "labs", "health", "app", "io"):
        stems.append("".join(words[:-1]))
    out: list[str] = []
    tlds = (".com", ".ai", ".io", ".co", ".co.uk", ".bio", ".tech")
    if sector and re.search(r"\bai\b|artificial", sector.lower()):
        tlds = (".ai",) + tuple(t for t in tlds if t != ".ai")
    elif sector and re.search(r"health|bio", sector.lower()):
        tlds = (".com", ".bio", ".health", ".ai", ".io", ".co", ".co.uk")
    for s in stems:
        for tld in tlds:
            if s.endswith("ai") and tld == ".ai" and len(s) > 4:
                out.append(s[:-2] + ".ai")
            out.append(s + tld)
    return list(dict.fromkeys(out))


def _fetch_job(key: str, domain: Optional[str], name: Optional[str], sector: Optional[str] = None) -> None:
    try:
        file = _fetch(key, domain, name, sector)
    except Exception:
        log.exception("logo fetch failed for %s", key)
        file = ""
    _remember(key, file or "")


def _fetch(key: str, domain: Optional[str], name: Optional[str], sector: Optional[str] = None) -> Optional[str]:
    import httpx

    with httpx.Client(timeout=5.0, follow_redirects=True, headers=_UA) as client:
        home = None
        if domain:
            home = _home(client, domain)
        elif name:
            want = _compact(name)
            for guess in _guess_domains(name, sector)[:16]:
                page = _home(client, guess)
                if page and want and (want in _compact(_title(page[0])) or
                                      _compact(_title(page[0])).startswith(want[: max(4, len(want) - 2)])):
                    domain, home = guess, page
                    break
            if not domain:
                return None
        assert domain
        img = None
        if home:
            for url in _candidates(home[0], home[1])[:6]:
                img = _get_image(client, url)
                if img:
                    break
        if not img:
            img = _get_image(client, f"https://{domain}/favicon.ico")
        if not img:
            img = _get_image(client, _GOOGLE.format(domain))
        if not img and home and _og_image(home[0], home[1]):  # last resort: often a wide banner
            img = _get_image(client, _og_image(home[0], home[1]))  # type: ignore[arg-type]
        if not img:
            return None
        data, ext = img
        SITE_LOGOS.mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^a-z0-9.-]", "_", domain.lower()) + "." + ext
        (SITE_LOGOS / fname).write_bytes(data)
        if key != domain:  # a name-only key also fills its domain key
            _remember(domain, fname)
        return fname


def wait_idle(timeout: float = 30.0) -> None:
    """Tests / scripts: wait for queued fetches."""
    import time

    end = time.monotonic() + timeout
    while _pending and time.monotonic() < end:
        time.sleep(0.2)
