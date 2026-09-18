import asyncio
from datetime import date

import pytest

from app.models import TravelRequest
from app.services import travel_service
from app.services.travel_scope import outside_travel_eligibility


@pytest.mark.parametrize("trip_type", ["normal", "training"])
def test_fixed_distance_is_not_used_for_outside_eligibility(monkeypatch, trip_type):
    async def fake_geocode(query: str):
        if query == "출발기관":
            return {
                "x": "127.0",
                "y": "36.8",
                "region_1depth_name": "충청남도",
                "region_2depth_name": "천안시 서북구",
                "resolved_name": "출발기관",
                "resolved_address": "충남 천안시 서북구 테스트로 1",
            }
        return {
            "x": "127.1",
            "y": "36.9",
            "region_1depth_name": "충청남도",
            "region_2depth_name": "아산시",
            "resolved_name": "목적기관",
            "resolved_address": "충남 아산시 테스트로 2",
        }

    async def fake_driving_distance(*_args):
        # 실제 출발지↔목적지 편도 5km = 왕복 10km, 따라서 관외여비 대상 아님.
        return 5.0, False

    monkeypatch.setattr(travel_service, "geocode", fake_geocode)
    monkeypatch.setattr(travel_service, "driving_distance", fake_driving_distance)
    monkeypatch.setattr(travel_service, "resolve_special_destination", lambda _value: None)
    monkeypatch.setattr(travel_service, "resolve_special_place", lambda *_args: None)
    monkeypatch.setattr(travel_service, "is_chungnam", lambda _value: True)
    monkeypatch.setattr(
        travel_service,
        "support_office_code",
        lambda sigungu: "CHEONAN" if "천안" in sigungu else "ASAN",
    )
    monkeypatch.setattr(
        travel_service,
        "destination_distance_code",
        lambda sigungu, _special: "ASAN" if "아산" in sigungu else "CHEONAN",
    )
    monkeypatch.setattr(travel_service, "fixed_distance_km", lambda _origin, _dest: 14.0)
    monkeypatch.setattr(travel_service, "support_office_label", lambda code: code)

    req = TravelRequest(
        travel_date=date(2026, 9, 18),
        origin="출발기관",
        destination="목적기관",
        vehicle_type="gasoline",
        trip_type=trip_type,
    )

    result = asyncio.run(travel_service.resolve_distance(req))

    # 운임 계산용 거리는 교육청 고정거리표를 유지한다.
    assert result.one_way_distance_km == 14.0
    assert result.distance_km == 28.0
    assert result.distance_source == "충청남도교육청 고정거리표"

    # 관외 판정은 실제 자동차 경로 왕복거리 10km를 사용한다.
    assert result.eligibility_round_trip_km == 10.0
    assert result.outside_travel_eligible is False
    assert "12km 미만" in result.outside_travel_reason


def test_outside_threshold_uses_unrounded_actual_distance():
    result = outside_travel_eligibility(
        origin_province="충청남도",
        origin_sigungu="천안시 서북구",
        destination_province="충청남도",
        destination_sigungu="아산시",
        one_way_km=5.99,
    )

    # 표시값은 12.0km로 보일 수 있어도 실제 왕복 11.98km이므로 탈락한다.
    assert result["round_trip_km"] == 12.0
    assert result["eligible"] is False


def test_outside_threshold_accepts_exactly_twelve_km():
    result = outside_travel_eligibility(
        origin_province="충청남도",
        origin_sigungu="천안시 서북구",
        destination_province="충청남도",
        destination_sigungu="아산시",
        one_way_km=6.0,
    )

    assert result["round_trip_km"] == 12.0
    assert result["eligible"] is True


def test_same_jurisdiction_is_never_outside_even_when_far():
    result = outside_travel_eligibility(
        origin_province="충청남도",
        origin_sigungu="천안시 서북구",
        destination_province="충청남도",
        destination_sigungu="천안시 동남구",
        one_way_km=20.0,
    )

    assert result["eligible"] is False
    assert "같은 행정구역" in result["reason"]
