from __future__ import annotations

from app.models import (
    DistanceResponse,
    EstimateResponse,
    PriceRequest,
    PriceResponse,
    TravelRequest,
)
from app.services.calculator import calculate_transport_cost
from app.services.chungnam_policy import (
    destination_distance_code,
    fixed_distance_km,
    is_chungnam,
    resolve_special_destination,
    support_office_code,
    support_office_label,
)
from app.services.kakao_service import driving_distance, geocode
from app.services.price_service import get_energy_price


async def resolve_distance(req: TravelRequest) -> DistanceResponse:
    origin = await geocode(req.origin)
    special_destination = resolve_special_destination(req.destination)
    destination_query = special_destination.canonical_address if special_destination else req.destination
    destination = await geocode(destination_query)

    origin_is_chungnam = is_chungnam(origin.get("region_1depth_name", ""))
    destination_is_chungnam = is_chungnam(destination.get("region_1depth_name", ""))
    origin_code = support_office_code(origin.get("region_2depth_name", "")) if origin_is_chungnam else None
    destination_code = destination_distance_code(
        destination.get("region_2depth_name", ""), special_destination
    ) if destination_is_chungnam else None

    fixed_one_way = fixed_distance_km(origin_code, destination_code) if (origin_is_chungnam and destination_is_chungnam) else None
    distance_cache_hit = False

    if fixed_one_way is not None:
        one_way_km = fixed_one_way
        distance_source = "충청남도교육청 고정거리표"
    else:
        one_way_km, distance_cache_hit = await driving_distance(
            origin["x"], origin["y"], destination["x"], destination["y"]
        )
        distance_source = (
            "카카오 길찾기(고정거리표 미등록 임시값)"
            if origin_is_chungnam and destination_is_chungnam
            else "카카오모빌리티 자동차 길찾기"
        )

    distance_km = one_way_km * (2 if req.round_trip else 1)
    province = destination.get("region_1depth_name", "")
    sigungu = destination.get("region_2depth_name", "")
    if special_destination and special_destination.canonical_sigungu:
        sigungu = special_destination.canonical_sigungu
    if not province or not sigungu:
        raise ValueError("출장지의 시도/시군구를 판별하지 못했습니다.")

    return DistanceResponse(
        distance_km=round(distance_km, 1),
        distance_source=distance_source,
        destination_code=destination_code,
        origin_support_office=support_office_label(origin_code),
        destination_support_office=(
            special_destination.label
            if special_destination
            else support_office_label(destination_code)
        ),
        distance_cache_hit=distance_cache_hit,
        province=province,
        sigungu=sigungu,
    )


async def resolve_price(req: PriceRequest) -> PriceResponse:
    price_result = await get_energy_price(
        req.travel_date,
        req.vehicle_type,
        req.province,
        req.sigungu,
    )
    amount = None
    if price_result["price"] is not None:
        amount = calculate_transport_cost(
            req.distance_km,
            req.efficiency,
            price_result["price"],
        )

    return PriceResponse(
        energy_price=price_result["price"],
        estimated_transport_cost=amount,
        price_source=price_result["source"],
        price_cache_hit=bool(price_result.get("cache_hit")),
        evidence_status=price_result["evidence_status"],
    )


async def estimate_travel(req: TravelRequest) -> EstimateResponse:
    distance = await resolve_distance(req)
    price = await resolve_price(
        PriceRequest(
            travel_date=req.travel_date,
            vehicle_type=req.vehicle_type,
            efficiency=req.efficiency,
            distance_km=distance.distance_km,
            province=distance.province,
            sigungu=distance.sigungu,
        )
    )

    return EstimateResponse(
        **distance.model_dump(),
        **price.model_dump(),
    )
