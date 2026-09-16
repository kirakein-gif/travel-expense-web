import httpx
from app.config import KAKAO_REST_API_KEY
LOCAL_URL = "https://dapi.kakao.com/v2/local/search/address.json"
DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
def _headers():
    if not KAKAO_REST_API_KEY:
        raise RuntimeError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
    return {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
async def geocode(address: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(LOCAL_URL, headers=_headers(), params={"query": address})
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if not docs:
            raise ValueError(f"주소를 찾을 수 없습니다: {address}")
        d = docs[0]
        addr = d.get("road_address") or d.get("address") or {}
        return {"x": d["x"], "y": d["y"], "address_name": addr.get("address_name", d.get("address_name", address)), "region_1depth_name": addr.get("region_1depth_name", ""), "region_2depth_name": addr.get("region_2depth_name", "")}
async def driving_distance(origin_x: str, origin_y: str, dest_x: str, dest_y: str) -> float:
    params = {"origin": f"{origin_x},{origin_y}", "destination": f"{dest_x},{dest_y}", "summary": "true", "priority": "RECOMMEND"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(DIRECTIONS_URL, headers=_headers(), params=params)
        r.raise_for_status()
        routes = r.json().get("routes", [])
        if not routes:
            raise ValueError("자동차 경로를 찾지 못했습니다.")
        return routes[0]["summary"]["distance"] / 1000.0
