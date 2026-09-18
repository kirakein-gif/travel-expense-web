from datetime import date

from app.services.ev_rate_service import get_electric_rate


def test_pre_reform_rate():
    rate = get_electric_rate(date(2026, 7, 31))
    assert rate["price"] == 324.4
    assert rate["effective_from"] == date(2022, 9, 1)


def test_reformed_rate_from_august_2026():
    rate = get_electric_rate(date(2026, 8, 1))
    assert rate["price"] == 325.6
    assert rate["effective_from"] == date(2026, 8, 1)


def test_latest_rate_for_current_period():
    rate = get_electric_rate(date(2026, 9, 18))
    assert rate["price"] == 325.6
    assert rate["source_updated_at"] == "2026-07-31"
