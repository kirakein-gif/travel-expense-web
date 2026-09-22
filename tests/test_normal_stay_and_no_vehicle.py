import asyncio
from datetime import date

from app.models import PriceRequest
from app.services.travel_policy import transport_distance
from app.services.travel_service import resolve_price


def _transport(mode: str):
    return transport_distance(
        one_way_km=10.0,
        start_date=date(2026, 9, 18),
        end_date=date(2026, 9, 19),
        trip_type="normal",
        round_trip=True,
        normal_stay_mode=mode,
        training_stay_mode="nonresidential",
        training_round_trips=None,
    )


def test_normal_multiday_nonresidential_uses_daily_round_trips():
    distance, count = _transport("nonresidential")
    assert distance == 40.0
    assert count == 2.0


def test_normal_multiday_residential_uses_one_round_trip():
    distance, count = _transport("residential")
    assert distance == 20.0
    assert count == 1.0


def _no_vehicle_request(**overrides):
    data = {
        "travel_date": date(2026, 9, 18),
        "end_date": date(2026, 9, 19),
        "vehicle_type": "gasoline",
        "no_vehicle": True,
        "distance_km": 40.0,
        "one_way_distance_km": 10.0,
        "round_trip": True,
        "province": "충청남도",
        "sigungu": "아산시",
        "origin_sigungu": "천안시",
        "trip_type": "normal",
        "normal_stay_mode": "residential",
        "toll_fee": 12000,
        "parking_fee": 5000,
        "lodging_fee": 40000,
    }
    data.update(overrides)
    return PriceRequest(**data)


def test_no_vehicle_skips_transport_price_and_vehicle_costs():
    result = asyncio.run(resolve_price(_no_vehicle_request()))
    assert result.energy_price is None
    assert result.estimated_transport_cost == 0
    assert result.transport_distance_km == 0
    assert result.round_trip_count == 0
    assert result.toll_fee == 0
    assert result.parking_fee == 0
    assert result.lodging_fee == 40000
    assert result.evidence_status == "no_vehicle"


def test_no_vehicle_does_not_apply_public_vehicle_daily_reduction():
    result = asyncio.run(resolve_price(_no_vehicle_request(public_vehicle=True)))
    assert result.daily_allowance == 50000


def test_same_day_forces_lodging_to_zero():
    result = asyncio.run(
        resolve_price(
            _no_vehicle_request(
                end_date=date(2026, 9, 18),
                lodging_fee=40000,
            )
        )
    )
    assert result.lodging_fee == 0
