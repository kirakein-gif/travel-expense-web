from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import (
    DistanceResponse,
    EstimateResponse,
    PriceRequest,
    PriceResponse,
    TravelRequest,
)
from app.services.calculator import calculate_repeated_transport_cost
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
from app.services.travel_scope import outside_travel_eligibility
from app.services.travel_policy import (
    calculate_allowances,
    get_vehicle_spec,
    transport_distance,
    trip_days,
)


def _seoul_today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _is_sejong(province_name: str) -> bool:
    return "세종" in (province_name or "").strip()


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

    # Sejong is a single-level special autonomous city. Kakao may return an
    # empty region_2depth_name or a road/eup/myeon token, but OPINET and travel
    # jurisdiction logic should consistently treat it as one region: 세종.
    if _is_sejong(province):
        sigungu = "세종"
    if _is_sejong(origin_province):
        origin_sigungu = "세종"

    if not province or not sigungu:
        raise ValueError("출장지의 시도/시군구를 판별하지 못했습니다.")

    eligibility = outside_travel_eligibility(
        origin_province=origin_province,
        origin_sigungu=origin_sigungu,
        destination_province=province,
        destination_sigungu=sigungu,
        one_way_km=one_way_km,
    )

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
        outside_travel_eligible=eligibility["eligible"],
        outside_travel_reason=eligibility["reason"],
        eligibility_round_trip_km=eligibility["round_trip_km"],
        origin_jurisdiction=eligibility["origin_jurisdiction"],
        destination_jurisdiction=eligibility["destination_jurisdiction"],
        resolved_origin_name=origin.get("resolved_name"),
        resolved_origin_address=origin.get("resolved_address") or origin.get("address_name"),
        resolved_destination_name=destination.get("resolved_name"),
        resolved_destination_address=destination.get("resolved_address") or destination.get("address_name"),
    )


def _formula(
    *,
    one_way_km: float,
    unit_price: float,
    efficiency: float,
    efficiency_unit: str,
    unit_cost: int,
    total_cost: int,
    round_trip_count: float,
    trip_type: str,
    training_stay_mode: str,
    days: int,
) -> str:
    price_unit = "원/L"
    if efficiency_unit == "km/kWh":
        price_unit = "원/kWh"
    elif efficiency_unit == "km/kg":
        price_unit = "원/kg"

    if round_trip_count == 0.5:
        return (
            f"{one_way_km:,.1f}km × {unit_price:,.2f}{price_unit} ÷ "
            f"{efficiency:g}{efficiency_unit} = {unit_cost:,.0f}원(10원 미만 절사)"
        )

    base = (
        f"{one_way_km:,.1f}km × {unit_price:,.2f}{price_unit} ÷ "
        f"{efficiency:g}{efficiency_unit} × 2회(왕복) = {unit_cost:,.0f}원(10원 미만 절사)"
    )

    if round_trip_count == 1:
        return base

    if int(round_trip_count) == days and (
        trip_type != "training" or training_stay_mode == "nonresidential"
    ):
        return f"{base} × {days}일 = {total_cost:,.0f}원"

    return f"{base} × {round_trip_count:g}회 = {total_cost:,.0f}원"


async def resolve_price(req: PriceRequest) -> PriceResponse:
    spec = get_vehicle_spec(req.vehicle_type, req.phev_energy_source)

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
        training_meal_claim_count=req.training_meal_claim_count,
        origin_sigungu=req.origin_sigungu,
        destination_sigungu=req.sigungu,
    )

    amount = None
    unit_cost = None
    formula = None

    if req.public_vehicle:
        price_result = {
            "price": None,
            "source": "공용차량 이용 · 단가조회 생략",
            "evidence_status": "not_required",
            "cache_hit": False,
        }
        amount = 0
        formula = "공용차량 이용: 자가용 자동차운임 지급하지 않음"
    else:
        today = _seoul_today()
        if req.travel_date > today and spec.price_vehicle_type in {"gasoline", "diesel", "lpg"}:
            raise ValueError("미래 날짜의 오피넷 유가는 조회할 수 없습니다.")

        if spec.price_vehicle_type == "hydrogen":
            if req.manual_energy_price is None:
                raise ValueError(
                    "수소차는 지역별 충전단가 차이가 커 자동단가를 적용하지 않습니다. "
                    "실제 충전단가 또는 확인 가능한 지역 수소단가를 직접 입력해주세요."
                )
            price_result = {
                "price": float(req.manual_energy_price),
                "source": "사용자 직접입력 · 수소 충전단가",
                "evidence_status": "manual_hydrogen_price",
                "cache_hit": False,
            }
        elif req.travel_date == today and spec.price_vehicle_type in {"gasoline", "diesel", "lpg"}:
            if req.manual_energy_price is None:
                raise ValueError(
                    "오피넷 당일 지역별 일평균 유가는 아직 제공되지 않습니다. "
                    "당일 출장신청은 적용 유가를 직접 입력해주세요."
                )
            price_result = {
                "price": float(req.manual_energy_price),
                "source": "사용자 수동입력 · 오피넷 당일 일평균 미제공",
                "evidence_status": "manual_price",
                "cache_hit": False,
            }
        else:
            price_result = await get_energy_price(
                req.travel_date,
                req.vehicle_type,
                req.province,
                req.sigungu,
                req.phev_energy_source,
            )

        if price_result["price"] is not None:
            unit_cost, amount = calculate_repeated_transport_cost(
                one_way_km=one_way_km,
                efficiency=float(spec.efficiency),
                unit_price=float(price_result["price"]),
                round_trip_count=round_trips,
            )
            formula = _formula(
                one_way_km=one_way_km,
                unit_price=float(price_result["price"]),
                efficiency=float(spec.efficiency),
                efficiency_unit=spec.efficiency_unit,
                unit_cost=unit_cost,
                total_cost=amount,
                round_trip_count=round_trips,
                trip_type=req.trip_type,
                training_stay_mode=req.training_stay_mode,
                days=trip_days(req.travel_date, req.end_date),
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
        fuel_price_date=(price_result.get("effective_from") or req.travel_date) if price_result["price"] is not None else None,
        vehicle_label=spec.label,
        effective_efficiency=float(spec.efficiency),
        efficiency_unit=spec.efficiency_unit,
        calculation_formula=formula,
        transport_unit_cost=unit_cost,
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
    if not distance.outside_travel_eligible:
        raise ValueError(distance.outside_travel_reason)

    price = await resolve_price(
        PriceRequest(
            travel_date=req.travel_date,
            end_date=req.end_date,
            vehicle_type=req.vehicle_type,
            phev_energy_source=req.phev_energy_source,
            efficiency=req.efficiency,
            manual_energy_price=req.manual_energy_price,
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
            training_meal_claim_count=req.training_meal_claim_count,
            toll_fee=req.toll_fee,
            parking_fee=req.parking_fee,
            lodging_fee=req.lodging_fee,
        )
    )

    return EstimateResponse(**distance.model_dump(), **price.model_dump())
