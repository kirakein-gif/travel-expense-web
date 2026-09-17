from __future__ import annotations

from datetime import date

from app.browser.opinet_browser import normalize_sigungu, query_opinet_region_prices
from app.config import OPINET_API_KEY
from app.services.cache_service import cache
from app.services.opinet_api_service import get_historical_area_price


def _find_sigungu_price(prices: dict[str, float], sigungu_name: str) -> float:
    target = normalize_sigungu(sigungu_name)
    candidates = [target]
    if " " in target:
        candidates.append(target.split(" ")[0])

    for name, price in prices.items():
        normalized = normalize_sigungu(name)
        if any(
            normalized == candidate
            or normalized.startswith(candidate)
            or normalized.endswith(candidate)
            or candidate.startswith(normalized)
            for candidate in candidates
        ):
            return float(price)

    preview = ", ".join(list(prices.keys())[:12]) or "(비어 있음)"
    raise RuntimeError(
        f"오피넷 캐시 가격표에서 {sigungu_name} 가격을 찾지 못했습니다. "
        f"추출된 지역: {preview}"
    )


async def _get_browser_price(
    travel_date: date,
    vehicle_type: str,
    province_name: str,
    sigungu_name: str,
) -> dict:
    cache_key = f"v3|{travel_date.isoformat()}|{province_name}|{vehicle_type}"

    async def factory() -> dict:
        result = await query_opinet_region_prices(
            travel_date=travel_date,
            province_name=province_name,
            vehicle_type=vehicle_type,
        )
        return {
            "prices": result.prices,
            "source_url": result.source_url,
            "evidence_path": result.evidence_path,
            "province": result.province,
            "product_label": result.product_label,
        }

    cached_result, cache_hit = await cache.get_or_create(
        "fuel_price",
        cache_key,
        factory,
        ttl_seconds=None if travel_date < date.today() else 21600,
    )

    price = _find_sigungu_price(cached_result["prices"], sigungu_name)
    return {
        "price": price,
        "source": "한국석유공사 오피넷 웹조회",
        "source_url": cached_result.get("source_url"),
        "evidence_status": "cached" if cache_hit else "captured",
        "evidence_path": cached_result.get("evidence_path"),
        "cache_hit": cache_hit,
    }


async def get_energy_price(
    travel_date: date,
    vehicle_type: str,
    province_name: str,
    sigungu_name: str,
) -> dict:
    if vehicle_type in {"gasoline", "diesel", "lpg"}:
        # 운영환경에서는 API가 가격 계산의 주 경로다. API가 실패했을 때
        # 사용자를 20~30초 더 기다리게 하지 않고 즉시 원인을 보여준다.
        # 웹 브라우저 조회/캡처는 별도의 증빙 단계로 분리한다.
        if OPINET_API_KEY:
            try:
                api_result = await get_historical_area_price(
                    travel_date=travel_date,
                    province_name=province_name,
                    sigungu_name=sigungu_name,
                    vehicle_type=vehicle_type,
                )
            except Exception as exc:
                raise RuntimeError(f"오피넷 API 조회 실패: {exc}") from exc

            return {
                "price": api_result["price"],
                "source": "한국석유공사 오피넷 API",
                "source_url": api_result.get("source_url"),
                "evidence_status": "api_price_ready",
                "evidence_path": None,
                "cache_hit": bool(api_result.get("cache_hit")),
            }

        # API 키가 없는 로컬 개발환경에서만 웹 조회를 임시 fallback으로 사용한다.
        return await _get_browser_price(
            travel_date,
            vehicle_type,
            province_name,
            sigungu_name,
        )

    if vehicle_type == "electric":
        return {
            "price": None,
            "source": "환경부 무공해차 통합누리집 급속충전요금 (연결 예정)",
            "source_url": None,
            "evidence_status": "official_rate_pending",
            "evidence_path": None,
            "cache_hit": False,
        }

    if vehicle_type == "hydrogen":
        return {
            "price": None,
            "source": "수소 공식가격 출처 (기관 규정 확인 후 연결)",
            "source_url": None,
            "evidence_status": "policy_pending",
            "evidence_path": None,
            "cache_hit": False,
        }

    raise ValueError(f"지원하지 않는 차량종류: {vehicle_type}")
