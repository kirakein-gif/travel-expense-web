import asyncio
from datetime import date

import pytest

from app.models import PriceRequest
from app.services.travel_service import resolve_price


def _request(**overrides):
    data = {
        "travel_date": date(2026, 9, 18),
        "end_date": date(2026, 9, 18),
        "vehicle_type": "electric",
        "distance_km": 20.0,
        "one_way_distance_km": 10.0,
        "round_trip": True,
        "province": "충청남도",
        "sigungu": "아산시",
        "origin_sigungu": "천안시",
    }
    data.update(overrides)
    return PriceRequest(**data)


def test_electric_uses_historical_official_rate():
    result = asyncio.run(resolve_price(_request()))
    assert result.energy_price == 325.6
    assert result.fuel_price_date == date(2026, 8, 1)
    assert result.evidence_status == "official_ev_rate"
    assert result.estimated_transport_cost == 1240
    assert "무공해차 통합누리집" in (result.price_source or "")


def test_hydrogen_uses_manual_price():
    result = asyncio.run(
        resolve_price(
            _request(
                vehicle_type="hydrogen",
                manual_energy_price=10000,
            )
        )
    )
    assert result.energy_price == 10000
    assert result.evidence_status == "manual_hydrogen_price"
    assert result.estimated_transport_cost == 2100


def test_hydrogen_requires_manual_price():
    with pytest.raises(ValueError, match="수소차"):
        asyncio.run(resolve_price(_request(vehicle_type="hydrogen")))
