from datetime import date
async def get_energy_price(travel_date: date, vehicle_type: str, destination_address: str) -> dict:
    if vehicle_type in {"gasoline", "diesel", "lpg"}:
        return {"price": None, "source": "한국석유공사 오피넷 (브라우저 자동조회 예정)", "evidence_status": "browser_automation_pending"}
    if vehicle_type == "electric":
        return {"price": None, "source": "환경부 무공해차 통합누리집 급속충전요금 (연결 예정)", "evidence_status": "official_rate_pending"}
    if vehicle_type == "hydrogen":
        return {"price": None, "source": "수소 공식가격 출처 (기관 규정 확인 후 연결)", "evidence_status": "policy_pending"}
    raise ValueError(f"지원하지 않는 차량종류: {vehicle_type}")
