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


def test_public_vehicle_clears_toll_and_parking_but_keeps_multiday_lodging():
    result = asyncio.run(
        resolve_price(
            _request(
                end_date=date(2026, 9, 19),
                public_vehicle=True,
                toll_fee=12000,
                parking_fee=5000,
                lodging_fee=40000,
            )
        )
    )
    assert result.estimated_transport_cost == 0
    assert result.toll_fee == 0
    assert result.parking_fee == 0
    assert result.lodging_fee == 40000


def test_same_day_clears_lodging_fee():
    result = asyncio.run(
        resolve_price(
            _request(
                toll_fee=1000,
                parking_fee=2000,
                lodging_fee=50000,
            )
        )
    )
    assert result.toll_fee == 1000
    assert result.parking_fee == 2000
    assert result.lodging_fee == 0
