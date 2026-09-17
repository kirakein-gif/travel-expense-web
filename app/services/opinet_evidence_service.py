from __future__ import annotations

import re
from pathlib import Path

from app.browser.opinet_browser import normalize_sigungu, query_opinet_region_prices


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def _matches_region(row_name: str, sigungu_name: str) -> bool:
    row = _compact(normalize_sigungu(row_name))
    target = _compact(normalize_sigungu(sigungu_name))
    if not row or not target:
        return False
    return row == target or row.endswith(target) or target.endswith(row) or target in row


async def generate_opinet_evidence(
    *,
    travel_date,
    province_name: str,
    sigungu_name: str,
    vehicle_type: str,
    expected_price: float,
    evidence_dir: str,
) -> str:
    if vehicle_type not in {"gasoline", "diesel", "lpg"}:
        raise ValueError("오피넷 증빙 생성은 휘발유·경유·LPG만 지원합니다.")

    result = await query_opinet_region_prices(
        travel_date=travel_date,
        province_name=province_name,
        vehicle_type=vehicle_type,
        evidence_dir=evidence_dir,
    )

    matched_name = None
    matched_price = None
    for row_name, row_price in result.prices.items():
        if _matches_region(row_name, sigungu_name):
            matched_name = row_name
            matched_price = float(row_price)
            break

    if matched_price is None:
        sample = ", ".join(list(result.prices.keys())[:12]) or "(비어 있음)"
        raise RuntimeError(
            f"오피넷 증빙 화면에서 {sigungu_name} 가격을 찾지 못했습니다. "
            f"추출된 지역: {sample}"
        )

    if abs(matched_price - float(expected_price)) > 0.05:
        raise RuntimeError(
            f"오피넷 증빙값이 API 계산값과 다릅니다. "
            f"{matched_name}: 화면 {matched_price:,.2f}원 / API {float(expected_price):,.2f}원"
        )

    path = Path(result.evidence_path)
    if not path.exists():
        raise RuntimeError("오피넷 증빙 이미지 파일이 생성되지 않았습니다.")
    return str(path)
