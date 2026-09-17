from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

import httpx

from app.config import KAKAO_REST_API_KEY
from app.services.cache_service import cache

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

# Institution searches are common in this app. These hints let us prefer the
# actual public/educational institution over a bank branch, parking lot, cafe,
# etc. that merely contains the same words in its place name.
PUBLIC_INSTITUTION_HINTS = (
    "시청", "도청", "군청", "구청", "교육청", "교육지원청", "지원청",
    "연수원", "교육원", "정보원", "의회", "학교", "유치원",
)
SPECIFIC_PLACE_TERMS = (
    "교육지원청", "교육연수원", "교육과정평가정보원", "연수원", "도의회",
    "시청", "도청", "군청", "구청", "교육청", "지원청", "의회",
    "유치원", "초등학교", "중학교", "고등학교", "대학교", "학교",
    "교육원", "정보원",
)
BUSINESS_WORDS = (
    "은행", "지점", "atm", "365코너", "주차장", "카페", "커피", "식당",
    "편의점", "부동산", "약국",
)
PUBLIC_CATEGORY_WORDS = ("사회,공공기관", "공공기관", "교육", "학교")

# Normalize common official/colloquial administrative names for comparison.
# City-level replacements intentionally keep the trailing "시" so that
# "부산광역시청" and "부산시청" become the same comparison key.
ADMIN_NAME_REPLACEMENTS = (
    ("세종특별자치시", "세종시"),
    ("서울특별시", "서울시"),
    ("부산광역시", "부산시"),
    ("대구광역시", "대구시"),
    ("인천광역시", "인천시"),
    ("광주광역시", "광주시"),
    ("대전광역시", "대전시"),
    ("울산광역시", "울산시"),
    ("충청남도", "충남"),
    ("충청북도", "충북"),
    ("전북특별자치도", "전북"),
    ("전라북도", "전북"),
    ("전라남도", "전남"),
    ("경상남도", "경남"),
    ("경상북도", "경북"),
    ("강원특별자치도", "강원"),
    ("강원도", "강원"),
    ("제주특별자치도", "제주"),
)

# Chungnam education-office staff often enter a parent organization plus a
# familiar short agency name, e.g. "충청남도교육청 충남교육연수원". Kakao may
# register the same place as either "충남교육연수원" or the official joined
# name "충청남도교육청교육연수원". Generate both forms before ranking.
CHUNGNAM_EDU_PARENT_NAMES = ("충청남도교육청", "충남교육청")


def _headers():
    if not KAKAO_REST_API_KEY:
        raise RuntimeError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
    return {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:32]


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def _name_key(value: str) -> str:
    """Comparison key tolerant of common Korean administrative name variants."""
    text = _compact(value)
    for full, short in ADMIN_NAME_REPLACEMENTS:
        text = text.replace(_compact(full), _compact(short))
    return text


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = re.sub(r"\s+", " ", (value or "").strip())
        if not value:
            continue
        key = _compact(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _institution_query_variants(query: str) -> list[str]:
    """Build a small set of realistic aliases for institution-place search.

    The original query is always first. Extra variants are intentionally
    conservative so normal place searches do not multiply API calls.
    """
    base = re.sub(r"\s+", " ", (query or "").strip())
    variants = [base]

    # Space-free form is useful because many Korean public institutions are
    # registered in Kakao without spaces in the official name.
    if " " in base:
        variants.append(_compact(base))

    for parent in CHUNGNAM_EDU_PARENT_NAMES:
        match = re.match(rf"^{re.escape(parent)}\s*(.+)$", base)
        if not match:
            continue

        child = match.group(1).strip()
        if not child:
            break

        # Familiar short agency name by itself, e.g. 충남교육연수원.
        variants.append(child)

        # Canonical official joined name. For a duplicated regional short name
        # (충남교육연수원), remove only the duplicated '충남' and retain
        # '교육연수원' -> 충청남도교육청교육연수원.
        official_child = child
        if _compact(child).startswith("충남"):
            official_child = child.replace("충남", "", 1).strip()
        variants.append(f"충청남도교육청{_compact(official_child)}")
        break

    return _unique(variants)


def _looks_like_address(query: str) -> bool:
    """Return True for practical road/lot-number address patterns.

    Place names such as '부산시청' or '충청남도교육청 교육연수원' should not be
    sent to the address API first because similar analysis can partially match
    another building. Real travel addresses almost always contain a number
    together with a road/lot administrative token.
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not re.search(r"\d", q):
        return False
    return bool(
        re.search(r"(?:대로|번길|길|로)\s*\d", q)
        or re.search(r"(?:동|리|가|읍|면)\s*\d", q)
        or re.search(r"\d+\s*번지", q)
    )


def _region_from_address_text(address_name: str) -> tuple[str, str]:
    """Extract a practical province/sigungu pair from Kakao keyword address text."""
    parts = re.sub(r"\s+", " ", (address_name or "").strip()).split(" ")
    if len(parts) < 2:
        return "", ""

    province = parts[0]
    sigungu = parts[1]

    # Keep district detail for places such as "천안시 서북구".
    if len(parts) >= 3 and parts[1].endswith("시") and parts[2].endswith("구"):
        sigungu = f"{parts[1]} {parts[2]}"

    return province, sigungu


def _keyword_score(query: str, doc: dict, index: int) -> float:
    target = _name_key(query)
    raw_target = _compact(query)
    name = _name_key(doc.get("place_name", ""))
    raw_name = _compact(doc.get("place_name", ""))
    category = (doc.get("category_name") or "").lower()

    # Keep Kakao's accuracy ordering as a meaningful tiebreaker.
    score = max(0, 40 - index * 2)

    if name == target:
        score += 1000
    else:
        score += SequenceMatcher(None, target, name).ratio() * 220

        if raw_target and raw_target in raw_name:
            score += 45
        if raw_name and raw_name in raw_target:
            score += 15

    public_query = any(word in raw_target for word in PUBLIC_INSTITUTION_HINTS)
    if public_query:
        if any(word.lower() in category for word in PUBLIC_CATEGORY_WORDS):
            score += 140
        if any(word in raw_name for word in BUSINESS_WORDS if word not in raw_target):
            score -= 260
        if any(word in category for word in BUSINESS_WORDS):
            score -= 180

    # If the user named a specific institution type, a parent institution that
    # omits that type should not win merely because it is a substring.
    for term in SPECIFIC_PLACE_TERMS:
        term_key = _name_key(term)
        if term_key in target and term_key not in name:
            score -= 180

    return score


def _best_keyword_document(query: str, docs: list[dict], variants: list[str] | None = None) -> tuple[dict, float]:
    if not docs:
        raise ValueError(f"장소를 찾을 수 없습니다: {query}")

    comparison_queries = variants or [query]
    ranked: list[tuple[float, dict]] = []
    for i, doc in enumerate(docs):
        # A candidate may be an exact match to an official or short-name variant
        # even when it is only a fuzzy match to the user's literal input.
        score = max(_keyword_score(q, doc, i) for q in comparison_queries)
        ranked.append((score, doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    score, doc = ranked[0]
    return doc, score


async def _keyword_documents(client: httpx.AsyncClient, query: str) -> list[dict]:
    r = await client.get(
        KEYWORD_URL,
        headers=_headers(),
        params={"query": query, "size": 15, "sort": "accuracy"},
    )
    r.raise_for_status()
    return r.json().get("documents", [])


async def _search_keyword(client: httpx.AsyncClient, query: str) -> tuple[dict, float]:
    variants = _institution_query_variants(query)

    # Always query the user's literal input first.
    docs = await _keyword_documents(client, variants[0])
    merged: dict[str, dict] = {}
    for d in docs:
        merged[d.get("id") or f"{d.get('x')}|{d.get('y')}|{d.get('place_name')}"] = d

    best, score = _best_keyword_document(query, list(merged.values()), variants)

    # For a recognized parent+short-agency pattern, query the extra aliases even
    # when the literal result looks superficially confident. This fixes cases
    # such as '충청남도교육청 충남교육연수원' selecting the parent office.
    parent_alias_case = len(variants) >= 3 and any(
        _compact(query).startswith(_compact(parent)) for parent in CHUNGNAM_EDU_PARENT_NAMES
    )

    # Otherwise, only spend one extra Kakao call when confidence is weak.
    extra_variants = variants[1:] if parent_alias_case else (variants[1:2] if score < 500 else [])

    for variant in extra_variants[:2]:
        more_docs = await _keyword_documents(client, variant)
        for d in more_docs:
            merged[d.get("id") or f"{d.get('x')}|{d.get('y')}|{d.get('place_name')}"] = d

    if len(merged) > len(docs):
        best, score = _best_keyword_document(query, list(merged.values()), variants)

    return best, score


async def geocode(query: str) -> dict:
    """Resolve a street address or institution/place name.

    Address-like input uses the address API. Institution/place input uses Kakao
    keyword search and a conservative post-ranking tuned for public institutions.
    """
    # v4 invalidates older 30-day cache entries produced by previous matchers.
    cache_key = _hash_key(f"geocode-v4|{query}")

    async def factory() -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            if _looks_like_address(query):
                r = await client.get(
                    ADDRESS_URL,
                    headers=_headers(),
                    params={"query": query, "analyze_type": "exact"},
                )
                r.raise_for_status()
                docs = r.json().get("documents", [])

                if not docs:
                    r = await client.get(
                        ADDRESS_URL,
                        headers=_headers(),
                        params={"query": query, "analyze_type": "similar"},
                    )
                    r.raise_for_status()
                    docs = r.json().get("documents", [])

                if docs:
                    d = docs[0]
                    addr = d.get("road_address") or d.get("address") or {}
                    resolved_address = addr.get("address_name", d.get("address_name", query))
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

            # Institution/place-name path (also fallback for an unresolved address).
            d, confidence = await _search_keyword(client, query)

            resolved_address = d.get("road_address_name") or d.get("address_name") or ""
            province, sigungu = _region_from_address_text(d.get("address_name") or resolved_address)

            if not resolved_address:
                raise ValueError(f"장소의 주소를 확인할 수 없습니다: {query}")

            return {
                "x": d["x"],
                "y": d["y"],
                "address_name": resolved_address,
                "resolved_name": d.get("place_name") or query,
                "resolved_address": resolved_address,
                "resolution_type": "keyword",
                "resolution_score": round(confidence, 1),
                "place_url": d.get("place_url"),
                "category_name": d.get("category_name"),
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
