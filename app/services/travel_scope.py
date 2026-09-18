from __future__ import annotations

from dataclasses import dataclass


METRO_MARKERS = ("특별시", "광역시")


@dataclass(frozen=True)
class TravelJurisdiction:
    key: str
    label: str


def travel_jurisdiction(province: str, sigungu: str) -> TravelJurisdiction:
    province = (province or "").strip()
    sigungu = (sigungu or "").strip()
    parts = [p for p in sigungu.split() if p]

    if "특별자치시" in province:
        return TravelJurisdiction(province or sigungu, province or sigungu)

    if any(marker in province for marker in METRO_MARKERS):
        unit = parts[0] if parts else province
        return TravelJurisdiction(f"{province}|{unit}", unit)

    unit = None
    for part in parts:
        if part.endswith(("시", "군")):
            unit = part
            break
    unit = unit or (parts[0] if parts else province)
    return TravelJurisdiction(f"{province}|{unit}", unit)


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
