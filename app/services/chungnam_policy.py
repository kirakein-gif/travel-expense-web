from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

MASTER_PATH = Path(__file__).resolve().parents[2] / "data" / "chungnam_distance_master.json"


@dataclass(frozen=True)
class SpecialDestination:
    code: str
    label: str
    canonical_address: str
    canonical_sigungu: str


@lru_cache(maxsize=1)
def load_master() -> dict:
    with MASTER_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def is_chungnam(region_1depth_name: str) -> bool:
    value = _compact(region_1depth_name)
    return value in {"충남", "충청남도"} or value.startswith("충청남도")


def resolve_special_destination(raw_destination: str) -> Optional[SpecialDestination]:
    compact = _compact(raw_destination)
    if not compact:
        return None

    master = load_master()
    for code, item in master.get("special_destinations", {}).items():
        aliases = item.get("aliases", [])
        for alias in aliases:
            alias_compact = _compact(alias)
            if alias_compact and alias_compact in compact:
                return SpecialDestination(
                    code=code,
                    label=item["label"],
                    canonical_address=item["canonical_address"],
                    canonical_sigungu=item.get("canonical_sigungu", ""),
                )
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
