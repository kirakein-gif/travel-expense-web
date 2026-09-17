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
    resolve_special_place,
    support_office_code,
    support_office_label,
)
from app.services.kakao_service import driving_distance, geocode
from app.services.price_service import get_energy_price
from app.services.travel_policy import (
    calculate_allowances,
    get_vehicle_spec,
    same_work_area,
    transport_distance,
)


async def resolve_distance(req: TravelRequest) -> DistanceResponse:
    origin_alias = resolve_special_destination(req.origin)
    destination_alias = resolve_special_destination(req.destination)

    origin_query = origin_alias.canonical_address if origin_alias else req.origin
    destination_query = destination_alias.canonical_address if destination_alias else req.destination

    origin = await geocode(origin_query)
    destination = await geocode(destination_query)

    special_origin = origin_alias or resolve_special_place(req.origin, origin)
    special_destination = destination_alias or resolve_special_place(req.destination, destination)

    origin_is_chungnam = is_chungnam(origin.get("region_1depth_name", ""))
    destination_is_chungnam = is_chungnam(destination.get("region_1depth_name", ""))

    if origin_is_chungnam:
        origin_code = special_origin.code if special_origin else support_office_code(origin.get("region_2depth_name", ""))
    else:
        origin_code = None

    if destination_is_chungnam:
        destination_code = destination_distance_code(
            destination.get("region_2depth_name", ""), special_destination
        )
    else:
        destination_code = None

    fixed_one_way = (
        fixed_distance_km(origin_code, destination_code)
        if (origin_is_chungnam and destination_is_chungnam)
        else None
    )
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

    provisional_distance = one_way_km * (2 if req.round_trip else 1)

    province = destination.get("region_1depth_name", "")
    sigungu = destination.get("region_2depth_name", "")
    origin_province = origin.get("region_1depth_name", "")
    origin_sigungu = origin.get("region_2depth_name", "")
    if not province or not sigungu:
        raise ValueError("출장지의 시도/시군구를 판별하지 못했습니다.")

    return DistanceResponse(
        one_way_distance_km=round(one_way_km, 1),
        distance_km=round(provisional_distance, 1),
        distance_source=distance_source,
        destination_code=destination_code,
        origin_support_office=(special_origin.label if special_origin else support_office_label(origin_code)),
        destination_support_office=(special_destination.label if special_destination else support_office_label(destination_code)),
        distance_cache_hit=distance_cache_hit,
        province=province,
        sigungu=sigungu,
        origin_province=origin_province,
        origin_sigungu=origin_sigungu,
        resolved_origin_name=origin.get("resolved_name"),
        resolved_origin_address=origin.get("resolved_address") or origin.get("address_name"),
        resolved_destination_name=destination.get("resolved_name"),
        resolved_destination_address=destination.get("resolved_address") or destination.get("address_name"),
    )


def _formula(distance_km: float, unit_price: float, efficiency: float, efficiency_unit: str, amount: int) -> str:
    price_unit = "원/L"
    if efficiency_unit == "km/kWh":
        price_unit = "원/kWh"
    elif efficiency_unit == "km/kg":
        price_unit = "원/kg"
    return (
        f"{distance_km:,.1f}km × {unit_price:,.2f}{price_unit} ÷ "
        f"{efficiency:g}{efficiency_unit} = {amount:,.0f}원"
    )


async def resolve_price(req: PriceRequest) -> PriceResponse:
    spec = get_vehicle_spec(req.vehicle_type, req.phev_energy_source)
    price_result = await get_energy_price(
        req.travel_date,
        req.vehicle_type,
        req.province,
        req.sigungu,
        req.phev_energy_source,
    )

    one_way_km = req.one_way_distance_km
    if one_way_km is None:
        one_way_km = req.distance_km / (2 if req.round_trip else 1)

    transport_km, round_trips = transport_distance(
        one_way_km=one_way_km,
        start_date=req.travel_date,
        end_date=req.end_date,
        trip_type=req.trip_type,
        round_trip=req.round_trip,
        training_stay_mode=req.training_stay_mode,
        training_round_trips=req.training_round_trips,
    )

    allowances = calculate_allowances(
        start_date=req.travel_date,
        end_date=req.end_date,
        trip_type=req.trip_type,
        public_vehicle=req.public_vehicle,
        provided_meals_count=req.provided_meals_count,
        training_stay_mode=req.training_stay_mode,
        training_round_trips=req.training_round_trips,
        training_meal_claim_amount=req.training_meal_claim_amount,
        origin_sigungu=req.origin_sigungu,
        destination_sigungu=req.sigungu,
    )

    amount = None
    formula = None
    training_inside = req.trip_type == "training" and same_work_area(req.origin_sigungu, req.sigungu)

    if training_inside:
        amount = 0
        formula = "교육훈련(근무지내 지역): 운임 지급하지 않음"
    elif req.public_vehicle:
        amount = 0
        formula = "공용차량 이용: 자가용 자동차운임 지급하지 않음"
    elif price_result["price"] is not None:
        amount = calculate_transport_cost(
            transport_km,
            float(spec.efficiency),
            price_result["price"],
        )
        formula = _formula(
            transport_km,
            float(price_result["price"]),
            float(spec.efficiency),
            spec.efficiency_unit,
            amount,
        )

    total = None
    if amount is not None:
        total = (
            amount
            + allowances["daily_allowance"]
            + allowances["meal_allowance"]
            + req.toll_fee
            + req.parking_fee
            + req.lodging_fee
        )

    return PriceResponse(
        energy_price=price_result["price"],
        estimated_transport_cost=amount,
        price_source=price_result["source"],
        price_cache_hit=bool(price_result.get("cache_hit")),
        evidence_status=price_result["evidence_status"],
        vehicle_label=spec.label,
        effective_efficiency=float(spec.efficiency),
        efficiency_unit=spec.efficiency_unit,
        calculation_formula=formula,
        transport_distance_km=transport_km,
        round_trip_count=round_trips,
        trip_days=allowances["trip_days"],
        daily_allowance=allowances["daily_allowance"],
        meal_allowance=allowances["meal_allowance"],
        toll_fee=req.toll_fee,
        parking_fee=req.parking_fee,
        lodging_fee=req.lodging_fee,
        total_expense=total,
        training_scope=allowances["training_scope"],
        daily_note=allowances["daily_note"],
        meal_note=allowances["meal_note"],
    )


async def estimate_travel(req: TravelRequest) -> EstimateResponse:
    distance = await resolve_distance(req)
    price = await resolve_price(
        PriceRequest(
            travel_date=req.travel_date,
            end_date=req.end_date,
            vehicle_type=req.vehicle_type,
            phev_energy_source=req.phev_energy_source,
            efficiency=req.efficiency,
            distance_km=distance.distance_km,
            one_way_distance_km=distance.one_way_distance_km,
            round_trip=req.round_trip,
            province=distance.province,
            sigungu=distance.sigungu,
            origin_sigungu=distance.origin_sigungu,
            trip_type=req.trip_type,
            public_vehicle=req.public_vehicle,
            provided_meals_count=req.provided_meals_count,
            training_stay_mode=req.training_stay_mode,
            training_round_trips=req.training_round_trips,
            training_meal_claim_amount=req.training_meal_claim_amount,
            toll_fee=req.toll_fee,
            parking_fee=req.parking_fee,
            lodging_fee=req.lodging_fee,
        )
    )

    return EstimateResponse(**distance.model_dump(), **price.model_dump())
