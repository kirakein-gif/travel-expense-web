from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

MASTER_PATH = Path(__file__).resolve().parents[2] / "data" / "chungnam_distance_master.json"
NAEPO_BOUNDARY_PATH = Path(__file__).resolve().parents[2] / "data" / "naepo_boundary.json"


@dataclass(frozen=True)
class SpecialDestination:
    code: str
    label: str
    canonical_address: str
    canonical_sigungu: str
    match_reason: str = "alias"


@lru_cache(maxsize=1)
def load_master() -> dict:
    with MASTER_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_naepo_boundary() -> dict:
    with NAEPO_BOUNDARY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def is_chungnam(region_1depth_name: str) -> bool:
    value = _compact(region_1depth_name)
    return value in {"충남", "충청남도"} or value.startswith("충청남도")


def _special_from_master(code: str, reason: str) -> Optional[SpecialDestination]:
    item = load_master().get("special_destinations", {}).get(code)
    if not item:
        return None
    return SpecialDestination(
        code=code,
        label=item["label"],
        canonical_address=item["canonical_address"],
        canonical_sigungu=item.get("canonical_sigungu", ""),
        match_reason=reason,
    )


def resolve_special_destination(raw_destination: str) -> Optional[SpecialDestination]:
    """Resolve explicit special-distance aliases such as Naepo.

    Special aliases must match the whole normalized input. A substring match is
    unsafe for parent-organization names. For example,
    '충청남도교육청 충남교육연수원' contains '충청남도교육청' but refers to a
    separate institution in Gongju and must not be forced to the Naepo office.
    """
    compact = _compact(raw_destination)
    if not compact:
        return None

    master = load_master()
    for code, item in master.get("special_destinations", {}).items():
        aliases = item.get("aliases", [])
        for alias in aliases:
            alias_compact = _compact(alias)
            if alias_compact and alias_compact == compact:
                return _special_from_master(code, "alias")
    return None


def _point_in_polygon(lon: float, lat: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon. Polygon coordinates are [lon, lat]."""
    if len(polygon) < 3:
        return False

    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            denominator = yj - yi
            if denominator != 0:
                x_intersection = (xj - xi) * (lat - yi) / denominator + xi
                if lon < x_intersection:
                    inside = not inside
        j = i
    return inside


def is_naepo_coordinate(x: str | float | None, y: str | float | None) -> bool:
    """Return True when a Kakao x/y point falls inside the Naepo boundary polygon."""
    try:
        lon = float(x) if x is not None else None
        lat = float(y) if y is not None else None
    except (TypeError, ValueError):
        return False
    if lon is None or lat is None:
        return False

    polygon = load_naepo_boundary().get("polygon", [])
    return _point_in_polygon(lon, lat, polygon)


def resolve_special_place(raw_text: str, geocoded: dict) -> Optional[SpecialDestination]:
    """Resolve an endpoint to a special distance code using alias first, then coordinates."""
    explicit = resolve_special_destination(raw_text)
    if explicit:
        return explicit

    if not is_chungnam(geocoded.get("region_1depth_name", "")):
        return None

    resolved_name = _compact(geocoded.get("resolved_name", ""))
    resolved_address = _compact(
        geocoded.get("resolved_address") or geocoded.get("address_name", "")
    )

    # If Kakao itself identifies the place/building as Naepo, accept that explicit place signal.
    if "내포신도시" in resolved_name or "내포신도시" in resolved_address:
        return _special_from_master("NAEPO", "place_name")

    if is_naepo_coordinate(geocoded.get("x"), geocoded.get("y")):
        return _special_from_master("NAEPO", "coordinate")

    return None


def normalize_sigungu(sigungu: str) -> str:
    value = re.sub(r"\s+", " ", (sigungu or "").strip())
    if not value:
        return ""

    first = value.split(" ")[0]
    if first.endswith(("시", "군")):
        return first
    return value


def support_office_code(sigungu: str) -> Optional[str]:
    normalized = normalize_sigungu(sigungu)
    master = load_master()

    for code, item in master.get("support_offices", {}).items():
        if normalized in item.get("sigungu", []):
            return code
    return None


def support_office_label(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    item = load_master().get("support_offices", {}).get(code)
    return item.get("label") if item else None


def destination_distance_code(
    sigungu: str,
    special_destination: Optional[SpecialDestination] = None,
) -> Optional[str]:
    if special_destination:
        return special_destination.code
    return support_office_code(sigungu)


def fixed_distance_km(origin_code: Optional[str], destination_code: Optional[str]) -> Optional[float]:
    if not origin_code or not destination_code:
        return None

    distances = load_master().get("distances_km", {})
    direct = f"{origin_code}|{destination_code}"
    reverse = f"{destination_code}|{origin_code}"

    value = distances.get(direct)
    if value is None:
        value = distances.get(reverse)

    if value is None:
        return None
    return float(value)
