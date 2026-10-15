from datetime import date

from app.models import Company, PortfolioItem, Signal
from app.portfolio_health import classify

TODAY = date(2026, 10, 1)


def _item(stage="Seed", website="x.com", health="good", signals=()):
    c = Company(id="x", name="X", one_liner="", sector="AI", stage=stage, website=website)
    return PortfolioItem(company=c, health=health, signals=list(signals))


def test_health_from_real_signals():
    assert classify(_item(stage="Acquired"), None, today=TODAY)[0] == "exited"
    assert classify(_item(website=None), None, today=TODAY)[0] == "at_risk"
    assert classify(_item(), {"site_status": "unreachable"}, today=TODAY)[0] == "at_risk"
    assert classify(_item(), {"last_funding_date": "2025-01-10"}, today=TODAY)[0] == "watch"
    assert classify(_item(), {"last_funding_date": "2026-05-01"}, today=TODAY)[0] == "good"
    assert classify(_item(), None, today=TODAY)[0] == "unknown"  # no signal: say so, don't guess "good"
    news = Signal(kind="strength", label="Big contract", icon="award", source_url="https://n.example")
    assert classify(_item(signals=[news]), None, today=TODAY)[0] == "good"
