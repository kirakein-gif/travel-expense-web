from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import OPINET_API_KEY
from app.services.cache_service import cache

API_BASE = "https://www.opinet.co.kr/api"
RECENT_AREA_ENDPOINT = "areaAvgRecentPrice.do"
DATE_AREA_ENDPOINT = "dateAreaAvgRecentPrice.do"
AREA_CODE_ENDPOINT = "areaCode.do"

PRODUCT_CODES = {
    "gasoline": "B027",
    "diesel": "D047",
    "lpg": "K015",
}

PROVINCE_ALIASES = {
    "서울특별시": "서울", "서울": "서울",
    "경기도": "경기", "경기": "경기",
    "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남",
    "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남",
    "부산광역시": "부산", "부산": "부산",
    "제주특별자치도": "제주", "제주": "제주",
    "대구광역시": "대구", "대구": "대구",
    "인천광역시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주": "광주",
    "대전광역시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종": "세종",
}


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    oil = payload.get("RESULT", {}).get("OIL", [])
    if isinstance(oil, dict):
        return [oil]
    if isinstance(oil, list):
        return oil
    return []


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _province_short(name: str) -> str:
    name = _clean(name)
    if name in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[name]
    for long_name, short_name in PROVINCE_ALIASES.items():
        if long_name in name:
            return short_name
    return name


async def _request_once(
    endpoint: str,
    auth_name: str,
    **extra: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {"out": "json", auth_name: OPINET_API_KEY}
    params.update({key: value for key, value in extra.items() if value})

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{API_BASE}/{endpoint}", params=params)
        response.raise_for_status()
        try:
            payload = json.loads(response.text, strict=False)
        except ValueError as exc:
            raise RuntimeError(
                f"오피넷 {endpoint}가 JSON 응답을 반환하지 않았습니다. API 키를 확인해주세요."
            ) from exc

    if not isinstance(payload, dict):
        return [], {}
    return _rows(payload), payload


async def check_opinet_api_status() -> dict[str, Any]:
    """Validate the configured API key without ever returning the secret value."""
    if not OPINET_API_KEY:
        return {
            "configured": False,
            "valid": False,
            "auth_mode": None,
            "area_count": 0,
            "message": "OPINET_API_KEY가 Cloud Run에 설정되지 않았습니다.",
        }

    attempts: list[str] = []
    for auth_name in ("certkey", "code"):
        try:
            rows, payload = await _request_once(AREA_CODE_ENDPOINT, auth_name)
            if rows:
                sample_names = [
                    _clean(row.get("AREA_NM"))
                    for row in rows[:5]
                    if _clean(row.get("AREA_NM"))
                ]
                return {
                    "configured": True,
                    "valid": True,
                    "auth_mode": auth_name,
                    "area_count": len(rows),
                    "sample_areas": sample_names,
                    "message": "오피넷 API 인증 및 지역코드 조회에 성공했습니다.",
                }

            result = payload.get("RESULT") if isinstance(payload, dict) else None
            result_text = _clean(result)
            if len(result_text) > 120:
                result_text = result_text[:120] + "..."
            attempts.append(f"{auth_name}: 데이터 없음" + (f" ({result_text})" if result_text else ""))
        except Exception as exc:
            text = str(exc)
            if len(text) > 120:
                text = text[:120] + "..."
            attempts.append(f"{auth_name}: {text}")

    return {
        "configured": True,
        "valid": False,
        "auth_mode": None,
        "area_count": 0,
        "message": "오피넷 API 인증 시험에 실패했습니다.",
        "attempts": attempts,
    }


async def _request(endpoint: str, **extra: str) -> list[dict[str, Any]]:
    if not OPINET_API_KEY:
        raise RuntimeError("OPINET_API_KEY가 설정되지 않았습니다.")

    # 현재 오피넷 일반 API 공식 문서는 certkey를 사용한다.
    rows, payload = await _request_once(endpoint, "certkey", **extra)
    if rows:
        return rows

    # 과거 통계 API의 예전 예제에는 code 파라미터가 사용된 적이 있어
    # 통계 엔드포인트에 한해서만 1회 호환 재시도를 한다.
    if endpoint in {RECENT_AREA_ENDPOINT, DATE_AREA_ENDPOINT}:
        legacy_rows, legacy_payload = await _request_once(endpoint, "code", **extra)
        if legacy_rows:
            return legacy_rows
        payload = legacy_payload or payload

    result = payload.get("RESULT") if isinstance(payload, dict) else None
    result_text = _clean(result)
    if len(result_text) > 180:
        result_text = result_text[:180] + "..."
    suffix = f" 응답: {result_text}" if result_text else ""
    raise RuntimeError(f"오피넷 {endpoint} 응답에 데이터가 없습니다.{suffix}")


def _name_matches(api_name: str, target: str) -> bool:
    api_name = _clean(api_name)
    target = _clean(target)
    if not api_name or not target:
        return False
    if api_name == target or api_name.endswith(target) or target.endswith(api_name):
        return True
    return target in api_name or api_name in target


async def _resolve_area_code(province_name: str, sigungu_name: str) -> str:
    cache_key = f"{_province_short(province_name)}|{_clean(sigungu_name)}"

    async def factory() -> str:
        province_short = _province_short(province_name)
        province_rows = await _request(AREA_CODE_ENDPOINT)
        province_code = None
        for row in province_rows:
            if _name_matches(row.get("AREA_NM", ""), province_short):
                province_code = _clean(row.get("AREA_CD"))
                break
        if not province_code:
            raise RuntimeError(f"오피넷 지역코드에서 {province_name}을(를) 찾지 못했습니다.")

        sigungu_rows = await _request(AREA_CODE_ENDPOINT, area=province_code)
        targets = [_clean(sigungu_name)]
        if " " in targets[0]:
            targets.append(targets[0].split(" ", 1)[0])

        for row in sigungu_rows:
            area_name = _clean(row.get("AREA_NM", ""))
            if any(_name_matches(area_name, target) for target in targets):
                area_code = _clean(row.get("AREA_CD"))
                if area_code:
                    return area_code

        sample = ", ".join(_clean(row.get("AREA_NM", "")) for row in sigungu_rows[:8])
        raise RuntimeError(
            f"오피넷 지역코드에서 {sigungu_name}을(를) 찾지 못했습니다. 조회 지역 예: {sample}"
        )

    value, _ = await cache.get_or_create(
        "opinet_area_code",
        cache_key,
        factory,
        ttl_seconds=None,
    )
    return str(value)


def _row_date(row: dict[str, Any]) -> str:
    return _clean(row.get("DATE") or row.get("TRADE_DT"))


async def get_historical_area_price(
    travel_date: date,
    province_name: str,
    sigungu_name: str,
    vehicle_type: str,
) -> dict[str, Any]:
    if vehicle_type not in PRODUCT_CODES:
        raise ValueError("오피넷 API 조회 대상 차량이 아닙니다.")

    area_code = await _resolve_area_code(province_name, sigungu_name)
    product_code = PRODUCT_CODES[vehicle_type]
    target_key = f"{travel_date.isoformat()}|{area_code}|{product_code}"

    cached = await cache.get("opinet_api_price", target_key)
    if cached is not None:
        return {**cached, "cache_hit": True}

    today = date.today()
    if today - timedelta(days=7) <= travel_date < today:
        endpoint = RECENT_AREA_ENDPOINT
    else:
        endpoint = DATE_AREA_ENDPOINT

    rows = await _request(
        endpoint,
        area=area_code,
        date=travel_date.strftime("%Y%m%d"),
        prodcd=product_code,
    )

    target_value = None
    available_dates: list[str] = []
    for row in rows:
        row_date = _row_date(row)
        row_product = _clean(row.get("PRODCD"))
        raw_price = row.get("PRICE")
        if row_date:
            available_dates.append(row_date)
        if len(row_date) != 8 or raw_price in (None, ""):
            continue
        if row_product and row_product != product_code:
            continue

        try:
            row_iso = f"{row_date[0:4]}-{row_date[4:6]}-{row_date[6:8]}"
            value = {
                "price": float(raw_price),
                "source": "한국석유공사 오피넷 API",
                "source_url": f"{API_BASE}/{endpoint}",
                "area_code": area_code,
                "api_date": row_iso,
                "endpoint": endpoint,
            }
            await cache.set(
                "opinet_api_price",
                f"{row_iso}|{area_code}|{product_code}",
                value,
                ttl_seconds=None,
            )
            if row_iso == travel_date.isoformat():
                target_value = value
        except (TypeError, ValueError):
            continue

    if target_value is None:
        available = ", ".join(sorted(set(available_dates))[:10]) or "없음"
        raise RuntimeError(
            f"오피넷 {endpoint} 응답에 {travel_date.isoformat()} 가격이 없습니다. 반환일자: {available}"
        )

    return {**target_value, "cache_hit": False}
