import asyncio
from datetime import date

import pytest

from app.services import opinet_api_service as api
from app.services import price_service as price


def test_validated_cache_bypasses_opinet_request(monkeypatch):
    async def fake_area(*args):
        return "041"

    async def fake_get(namespace, key):
        assert namespace == api.VALIDATED_PRICE_NAMESPACE
        return {
            "price": 1680.2,
            "source_url": "u",
            "area_code": "041",
            "api_date": "2026-09-22",
            "endpoint": "x",
            "product_code": "B027",
            "validated": True,
        }

    async def fail_request(*args, **kwargs):
        raise AssertionError("OPINET API must not be called on validated cache hit")

    monkeypatch.setattr(api, "_resolve_area_code", fake_area)
    monkeypatch.setattr(api.cache, "get", fake_get)
    monkeypatch.setattr(api, "_request", fail_request)

    result = asyncio.run(
        api.get_historical_area_price(
            date(2026, 9, 22), "충청남도", "아산시", "gasoline"
        )
    )
    assert result["price"] == 1680.2
    assert result["cache_hit"] is True


def test_api_and_web_match_is_saved(monkeypatch):
    saved = {}

    async def fake_api(**kwargs):
        return {
            "price": 1680.2,
            "cache_hit": False,
            "api_date": "2026-09-22",
            "area_code": "041",
            "product_code": "B027",
        }

    async def fake_web(*args, **kwargs):
        return {"price": 1680.2, "source_url": "web", "cache_hit": False}

    async def fake_save(api_result, **kwargs):
        saved.update(kwargs)
        return {**api_result, "validated": True, "source_url": "api"}

    monkeypatch.setattr(price, "get_historical_area_price", fake_api)
    monkeypatch.setattr(price, "_get_browser_price", fake_web)
    monkeypatch.setattr(price, "save_validated_historical_area_price", fake_save)

    result = asyncio.run(
        price.get_energy_price(
            date(2026, 9, 22), "gasoline", "충청남도", "아산시"
        )
    )
    assert result["price"] == 1680.2
    assert result["cache_hit"] is False
    assert saved["web_price"] == 1680.2
    assert "웹 검증 완료" in result["source"]


def test_api_and_web_mismatch_is_rejected(monkeypatch):
    called = {"save": False}

    async def fake_api(**kwargs):
        return {
            "price": 1680.2,
            "cache_hit": False,
            "api_date": "2026-09-22",
            "area_code": "041",
            "product_code": "B027",
        }

    async def fake_web(*args, **kwargs):
        return {"price": 1681.2, "source_url": "web", "cache_hit": False}

    async def fake_save(*args, **kwargs):
        called["save"] = True
        return {}

    monkeypatch.setattr(price, "get_historical_area_price", fake_api)
    monkeypatch.setattr(price, "_get_browser_price", fake_web)
    monkeypatch.setattr(price, "save_validated_historical_area_price", fake_save)

    with pytest.raises(RuntimeError, match="일치하지 않습니다"):
        asyncio.run(
            price.get_energy_price(
                date(2026, 9, 22), "gasoline", "충청남도", "아산시"
            )
        )
    assert called["save"] is False
