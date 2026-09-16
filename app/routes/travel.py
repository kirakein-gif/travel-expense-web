from fastapi import APIRouter, HTTPException
from app.models import TravelRequest, EstimateResponse
from app.services.kakao_service import geocode, driving_distance
from app.services.calculator import calculate_transport_cost
from app.services.price_service import get_energy_price

router = APIRouter(tags=["travel"])

@router.post("/estimate", response_model=EstimateResponse)
async def estimate(req: TravelRequest):
    try:
        origin = await geocode(req.origin)
        destination = await geocode(req.destination)
        one_way_km = await driving_distance(origin["x"], origin["y"], destination["x"], destination["y"])
        distance_km = one_way_km * (2 if req.round_trip else 1)
        province = destination.get("region_1depth_name", "")
        sigungu = destination.get("region_2depth_name", "")
        if not province or not sigungu:
            raise ValueError("출장지의 시도/시군구를 판별하지 못했습니다.")
        price_result = await get_energy_price(req.travel_date, req.vehicle_type, province, sigungu)
        amount = None
        if price_result["price"] is not None:
            amount = calculate_transport_cost(distance_km, req.efficiency, price_result["price"])
        return EstimateResponse(distance_km=round(distance_km, 1), energy_price=price_result["price"], estimated_transport_cost=amount, price_source=price_result["source"], evidence_status=price_result["evidence_status"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
