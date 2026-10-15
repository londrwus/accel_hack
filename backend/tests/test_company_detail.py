from app.tools import logos


def test_company_detail_shape(client):
    r = client.get("/api/companies/northbeam-health/detail")
    assert r.status_code == 200
    d = r.json()
    assert d["company"]["id"] == "northbeam-health"
    assert d["company"]["logo"] is None  # made-up demo company: never a logo
    assert {"score", "signals", "similar", "sources", "funding", "market"} <= d.keys()
    assert isinstance(d["score"]["scored"], bool) and d["score"]["source_label"]


def test_company_detail_404(client):
    r = client.get("/api/companies/no-such-company-xyz/detail")
    assert r.status_code == 404 and r.json()["error"]


def test_logo_routes_reject_paths(client):
    assert client.get("/api/logos/site/..%2F..%2F.env").status_code == 404
    assert client.get("/api/logos/dataset/missing.png").status_code == 404


def test_resolve_never_blocks_and_never_guesses_for_unknown_names():
    assert logos.resolve(None, None) is None
    url = logos.resolve("Some Company", "example.org", fetch=False)
    assert url is None or url.startswith("/api/logos/")
