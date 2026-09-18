from __future__ import annotations

from dataclasses import dataclass


METRO_PROVINCES = {
    "서울", "서울특별시",
    "부산", "부산광역시",
    "대구", "대구광역시",
    "인천", "인천광역시",
    "광주", "광주광역시",
    "대전", "대전광역시",
    "울산", "울산광역시",
}
SEJONG_NAMES = {"세종", "세종시", "세종특별자치시"}

PROVINCE_ALIASES = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종", "세종시": "세종",
    "충청남도": "충남", "충청북도": "충북", "전라남도": "전남",
    "전라북도": "전북", "전북특별자치도": "전북", "경상남도": "경남",
    "경상북도": "경북", "강원도": "강원", "강원특별자치도": "강원",
    "제주특별자치도": "제주",
}


@dataclass(frozen=True)
class TravelJurisdiction:
    key: str
    label: str


def travel_jurisdiction(province: str, sigungu: str) -> TravelJurisdiction:
    province = (province or "").strip()
    province_key = PROVINCE_ALIASES.get(province, province)
    sigungu = (sigungu or "").strip()
    parts = [p for p in sigungu.split() if p]

    if province in SEJONG_NAMES or province_key == "세종":
        return TravelJurisdiction("세종", "세종")

    if province in METRO_PROVINCES or province_key in METRO_PROVINCES:
        unit = parts[0] if parts else province_key
        return TravelJurisdiction(f"{province_key}|{unit}", unit)

    unit = None
    for part in parts:
        if part.endswith(("시", "군")):
            unit = part
            break
    unit = unit or (parts[0] if parts else province)
    return TravelJurisdiction(f"{province_key}|{unit}", unit)


def outside_travel_eligibility(
    *,
    origin_province: str,
    origin_sigungu: str,
    destination_province: str,
    destination_sigungu: str,
    one_way_km: float,
) -> dict:
    origin = travel_jurisdiction(origin_province, origin_sigungu)
    destination = travel_jurisdiction(destination_province, destination_sigungu)
    round_trip_km = round(float(one_way_km) * 2, 1)

    if origin.key == destination.key:
        return {
            "eligible": False,
            "reason": (
                f"출발지와 출장지가 같은 행정구역({origin.label})입니다. "
                "이 프로그램의 관외여비 지급 대상이 아닙니다."
            ),
            "round_trip_km": round_trip_km,
            "origin_jurisdiction": origin.label,
            "destination_jurisdiction": destination.label,
        }

    if round_trip_km < 12:
        return {
            "eligible": False,
            "reason": (
                f"1회 왕복 여행거리가 {round_trip_km:g}km로 12km 미만입니다. "
                "출장일수와 관계없이 1회 왕복거리 기준으로 관외여비 지급 대상이 아닙니다."
            ),
            "round_trip_km": round_trip_km,
            "origin_jurisdiction": origin.label,
            "destination_jurisdiction": destination.label,
        }

    return {
        "eligible": True,
        "reason": (
            f"행정구역 이동({origin.label} → {destination.label}) · "
            f"1회 왕복 {round_trip_km:g}km"
        ),
        "round_trip_km": round_trip_km,
        "origin_jurisdiction": origin.label,
        "destination_jurisdiction": destination.label,
    }
