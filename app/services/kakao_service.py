from __future__ import annotations

import hashlib
import re

import httpx

from app.config import KAKAO_REST_API_KEY
from app.services.cache_service import cache

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"


def _headers():
    if not KAKAO_REST_API_KEY:
        raise RuntimeError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
    return {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:32]


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def _region_from_address_text(address_name: str) -> tuple[str, str]:
    """Extract a practical province/sigungu pair from Kakao keyword address text.

    Keyword search already returns coordinates and full addresses but not the
    region_1depth_name / region_2depth_name fields returned by address search.
    For travel policy lookup we only need province and the city/county unit.
    """
    parts = re.sub(r"\s+", " ", (address_name or "").strip()).split(" ")
    if len(parts) < 2:
        return "", ""

    province = parts[0]
    sigungu = parts[1]

    # Keep district detail when Kakao returns a metropolitan city subdivision
    # such as "천안시 서북구". The policy normalizer can still reduce it to 천안시.
    if len(parts) >= 3 and parts[1].endswith("시") and parts[2].endswith("구"):
        sigungu = f"{parts[1]} {parts[2]}"

    return province, sigungu


def _best_keyword_document(query: str, docs: list[dict]) -> dict:
    """Prefer an exact/near-exact place-name match before Kakao's first result."""
    target = _compact(query)
    if not docs:
        raise ValueError(f"장소를 찾을 수 없습니다: {query}")

    for doc in docs:
        if _compact(doc.get("place_name", "")) == target:
            return doc

    for doc in docs:
        name = _compact(doc.get("place_name", ""))
        if target and (target in name or name in target):
            return doc

    return docs[0]


async def geocode(query: str) -> dict:
    """Resolve either a street address or an institution/place name.

    Address search is attempted first so existing address-based use stays cheap.
    If it returns no documents, Kakao keyword place search is used and its
    address/coordinates are normalized for the rest of the travel pipeline.
    """
    cache_key = _hash_key(query)

    async def factory() -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            # 1) Exact address path — one API call for normal road/lot addresses.
            r = await client.get(
                ADDRESS_URL,
                headers=_headers(),
                params={"query": query},
            )
            r.raise_for_status()
            docs = r.json().get("documents", [])

            if docs:
                d = docs[0]
                addr = d.get("road_address") or d.get("address") or {}
                resolved_address = addr.get(
                    "address_name", d.get("address_name", query)
                )
                return {
                    "x": d["x"],
                    "y": d["y"],
                    "address_name": resolved_address,
                    "resolved_name": resolved_address,
                    "resolved_address": resolved_address,
                    "resolution_type": "address",
                    "region_1depth_name": addr.get("region_1depth_name", ""),
                    "region_2depth_name": addr.get("region_2depth_name", ""),
                }

            # 2) Institution/place-name path.
            r = await client.get(
                KEYWORD_URL,
                headers=_headers(),
                params={"query": query, "size": 15},
            )
            r.raise_for_status()
            place_docs = r.json().get("documents", [])
            d = _best_keyword_document(query, place_docs)

            resolved_address = (
                d.get("road_address_name")
                or d.get("address_name")
                or ""
            )
            province, sigungu = _region_from_address_text(
                d.get("address_name") or resolved_address
            )

            if not resolved_address:
                raise ValueError(f"장소의 주소를 확인할 수 없습니다: {query}")

            return {
                "x": d["x"],
                "y": d["y"],
                "address_name": resolved_address,
                "resolved_name": d.get("place_name") or query,
                "resolved_address": resolved_address,
                "resolution_type": "keyword",
                "region_1depth_name": province,
                "region_2depth_name": sigungu,
            }

    value, _ = await cache.get_or_create(
        "geocode",
        cache_key,
        factory,
        ttl_seconds=60 * 60 * 24 * 30,
    )
    return value


async def driving_distance(
    origin_x: str,
    origin_y: str,
    dest_x: str,
    dest_y: str,
) -> tuple[float, bool]:
    route_text = f"{origin_x},{origin_y}|{dest_x},{dest_y}"
    cache_key = _hash_key(route_text)

    async def factory() -> float:
        params = {
            "origin": f"{origin_x},{origin_y}",
            "destination": f"{dest_x},{dest_y}",
            "summary": "true",
            "priority": "RECOMMEND",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(DIRECTIONS_URL, headers=_headers(), params=params)
            r.raise_for_status()
            routes = r.json().get("routes", [])
            if not routes:
                raise ValueError("자동차 경로를 찾지 못했습니다.")
            return routes[0]["summary"]["distance"] / 1000.0

    value, cache_hit = await cache.get_or_create(
        "driving_distance",
        cache_key,
        factory,
        ttl_seconds=60 * 60 * 24 * 30,
    )
    return float(value), cache_hit
