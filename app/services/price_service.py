from __future__ import annotations

from datetime import date

from app.browser.opinet_browser import normalize_sigungu, query_opinet_region_prices
from app.services.cache_service import cache


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
            or candidate.startswith(normalized)
            for candidate in candidates
        ):
            return float(price)

    raise RuntimeError(f"오피넷 캐시 가격표에서 {sigungu_name} 가격을 찾지 못했습니다.")


async def get_energy_price(
    travel_date: date,
    vehicle_type: str,
    province_name: str,
    sigungu_name: str,
) -> dict:
    if vehicle_type in {"gasoline", "diesel", "lpg"}:
        cache_key = f"{travel_date.isoformat()}|{province_name}|{vehicle_type}"

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
            "source": "한국석유공사 오피넷",
            "source_url": cached_result.get("source_url"),
            "evidence_status": "cached" if cache_hit else "captured",
            "evidence_path": cached_result.get("evidence_path"),
            "cache_hit": cache_hit,
        }

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
