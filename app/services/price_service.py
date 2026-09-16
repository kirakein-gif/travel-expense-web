from datetime import date
from app.browser.opinet_browser import query_opinet_price

async def get_energy_price(travel_date: date, vehicle_type: str, province_name: str, sigungu_name: str) -> dict:
    if vehicle_type in {"gasoline", "diesel", "lpg"}:
        result = await query_opinet_price(travel_date, province_name, sigungu_name, vehicle_type)
        return {"price": result.price, "source": "한국석유공사 오피넷", "source_url": result.source_url, "evidence_status": "captured", "evidence_path": result.evidence_path}
    if vehicle_type == "electric":
        return {"price": None, "source": "환경부 무공해차 통합누리집 급속충전요금 (연결 예정)", "source_url": None, "evidence_status": "official_rate_pending", "evidence_path": None}
    if vehicle_type == "hydrogen":
        return {"price": None, "source": "수소 공식가격 출처 (기관 규정 확인 후 연결)", "source_url": None, "evidence_status": "policy_pending", "evidence_path": None}
    raise ValueError(f"지원하지 않는 차량종류: {vehicle_type}")
