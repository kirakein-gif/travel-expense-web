from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.browser.opinet_browser import (
    normalize_province,
    normalize_sigungu,
    query_opinet_region_prices,
)
from app.config import OPINET_API_KEY
from app.services.cache_service import cache
from app.services.opinet_api_service import (
    get_historical_area_price,
    save_validated_historical_area_price,
)
from app.services.ev_rate_service import get_electric_rate
from app.services.travel_policy import get_vehicle_spec


def _seoul_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _ensure_opinet_date_available(travel_date: date) -> None:
    if travel_date >= _seoul_today():
        raise ValueError(
            "오피넷 지역별 일평균 유가는 당일 자료가 제공되지 않습니다. "
            "출장 시작일을 전일 또는 이전 날짜로 선택해주세요."
        )


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

    if "세종" in target and len(prices) == 1:
        return float(next(iter(prices.values())))

    preview = ", ".join(list(prices.keys())[:12]) or "(비어 있음)"
    raise RuntimeError(
        f"오피넷 캐시 가격표에서 {sigungu_name} 가격을 찾지 못했습니다. "
        f"추출된 지역: {preview}"
    )


async def _get_browser_price(
    travel_date: date,
    lookup_vehicle_type: str,
    province_name: str,
    sigungu_name: str,
) -> dict:
    _ensure_opinet_date_available(travel_date)
    normalized_province = normalize_province(province_name)
    cache_key = f"v5|{travel_date.isoformat()}|{normalized_province}|{lookup_vehicle_type}"

    async def factory() -> dict:
        result = await query_opinet_region_prices(
            travel_date=travel_date,
            province_name=province_name,
            vehicle_type=lookup_vehicle_type,
        )
        return {
            "prices": result.prices,
            "source_url": result.source_url,
            "province": result.province,
            "product_label": result.product_label,
        }

    # A historical OPINET daily average does not change after publication.
    # Cache the full province table permanently so validating a second city on
    # the same date/fuel does not require another browser lookup.
    cached_result, cache_hit = await cache.get_or_create(
        "fuel_price",
        cache_key,
        factory,
        ttl_seconds=None,
    )

    price = _find_sigungu_price(cached_result["prices"], sigungu_name)
    return {
        "price": price,
        "source": "한국석유공사 오피넷 웹조회",
        "source_url": cached_result.get("source_url"),
        "evidence_status": "cached" if cache_hit else "captured",
        "evidence_path": None,
        "cache_hit": cache_hit,
    }


async def _validate_api_price(
    *,
    travel_date: date,
    lookup_vehicle_type: str,
    province_name: str,
    sigungu_name: str,
    api_result: dict,
) -> dict:
    try:
        web_result = await _get_browser_price(
            travel_date,
            lookup_vehicle_type,
            province_name,
            sigungu_name,
        )
    except Exception as exc:
        raise RuntimeError(
            "오피넷 API 가격은 조회했지만 웹페이지 대조 검증에 실패했습니다. "
            "검증되지 않은 값은 공유 캐시에 저장하지 않습니다. "
            f"({exc})"
        ) from exc

    api_price = float(api_result["price"])
    web_price = float(web_result["price"])
    if abs(api_price - web_price) > 0.011:
        raise RuntimeError(
            "오피넷 API 가격과 웹페이지 가격이 일치하지 않습니다. "
            "검증되지 않은 값은 사용하거나 공유 캐시에 저장하지 않습니다. "
            f"API {api_price:,.2f}원 / 웹 {web_price:,.2f}원"
        )

    validated = await save_validated_historical_area_price(
        api_result,
        web_price=web_price,
        province_name=province_name,
        sigungu_name=sigungu_name,
        vehicle_type=lookup_vehicle_type,
        web_source_url=web_result.get("source_url"),
    )
    return {**validated, "cache_hit": False}


async def get_energy_price(
    travel_date: date,
    vehicle_type: str,
    province_name: str,
    sigungu_name: str,
    phev_energy_source: str | None = None,
) -> dict:
    spec = get_vehicle_spec(vehicle_type, phev_energy_source)
    lookup_vehicle_type = spec.price_vehicle_type

    if lookup_vehicle_type in {"gasoline", "diesel", "lpg"}:
        _ensure_opinet_date_available(travel_date)
        if OPINET_API_KEY:
            try:
                api_result = await get_historical_area_price(
                    travel_date=travel_date,
                    province_name=province_name,
                    sigungu_name=sigungu_name,
                    vehicle_type=lookup_vehicle_type,
                )
                if not api_result.get("cache_hit"):
                    api_result = await _validate_api_price(
                        travel_date=travel_date,
                        lookup_vehicle_type=lookup_vehicle_type,
                        province_name=province_name,
                        sigungu_name=sigungu_name,
                        api_result=api_result,
                    )
            except Exception as exc:
                raise RuntimeError(f"오피넷 유가 조회/검증 실패: {exc}") from exc

            sejong_scope = "세종" in (province_name or "")
            source = (
                "한국석유공사 오피넷 검증 캐시"
                if api_result.get("cache_hit")
                else "한국석유공사 오피넷 API · 웹 검증 완료"
            )
            if sejong_scope:
                source += " · 세종시 평균"
            return {
                "price": api_result["price"],
                "source": source,
                "source_url": api_result.get("source_url"),
                "evidence_status": "api_price_ready",
                "evidence_path": None,
                "cache_hit": bool(api_result.get("cache_hit")),
            }

        return await _get_browser_price(
            travel_date,
            lookup_vehicle_type,
            province_name,
            sigungu_name,
        )

    if lookup_vehicle_type == "electric":
        rate = get_electric_rate(travel_date)
        updated = rate.get("source_updated_at")
        source = (
            f'무공해차 통합누리집 · {rate["provider"]} {rate["rate_label"]}'
            + (f" · 갱신 {updated}" if updated else "")
        )
        return {
            "price": rate["price"],
            "source": source,
            "source_url": rate.get("source_url"),
            "evidence_status": "official_ev_rate",
            "evidence_path": None,
            "cache_hit": False,
            "effective_from": rate["effective_from"],
        }

    if lookup_vehicle_type == "hydrogen":
        return {
            "price": None,
            "source": "수소단가 사용자 직접입력",
            "source_url": None,
            "evidence_status": "manual_hydrogen_price",
            "evidence_path": None,
            "cache_hit": False,
        }

    raise ValueError(f"지원하지 않는 차량종류: {vehicle_type}")
