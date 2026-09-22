from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

DAILY_ALLOWANCE_RATE = Decimal("25000")
MEAL_ALLOWANCE_RATE = Decimal("25000")


@dataclass(frozen=True)
class VehicleSpec:
    label: str
    efficiency: Decimal
    efficiency_unit: str
    price_unit: str
    price_vehicle_type: str


VEHICLE_SPECS = {
    "gasoline": VehicleSpec("휘발유", Decimal("11.97"), "km/L", "원/L", "gasoline"),
    "diesel": VehicleSpec("경유", Decimal("12.52"), "km/L", "원/L", "diesel"),
    "lpg": VehicleSpec("LPG", Decimal("8.83"), "km/L", "원/L", "lpg"),
    "hybrid": VehicleSpec("하이브리드", Decimal("15.37"), "km/L", "원/L", "gasoline"),
    "electric": VehicleSpec("전기", Decimal("5.22"), "km/kWh", "원/kWh", "electric"),
    "hydrogen": VehicleSpec("수소", Decimal("94.9"), "km/kg", "원/kg", "hydrogen"),
}

PHEV_SPECS = {
    "gasoline": VehicleSpec("플러그인하이브리드(휘발유)", Decimal("10.61"), "km/L", "원/L", "gasoline"),
    "electric": VehicleSpec("플러그인하이브리드(전기)", Decimal("2.84"), "km/kWh", "원/kWh", "electric"),
}


def _won(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_vehicle_spec(vehicle_type: str, phev_energy_source: str | None = None) -> VehicleSpec:
    if vehicle_type == "phev":
        key = phev_energy_source or "gasoline"
        if key not in PHEV_SPECS:
            raise ValueError("플러그인하이브리드는 휘발유 또는 전기 중 하나를 선택해야 합니다.")
        return PHEV_SPECS[key]
    try:
        return VEHICLE_SPECS[vehicle_type]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 차량종류: {vehicle_type}") from exc


def trip_days(start_date: date, end_date: date | None) -> int:
    end = end_date or start_date
    if end < start_date:
        raise ValueError("출장 종료일은 시작일보다 빠를 수 없습니다.")
    return (end - start_date).days + 1


def same_work_area(origin_sigungu: str, destination_sigungu: str) -> bool:
    def norm(value: str) -> str:
        return (value or "").strip().split(" ")[0]
    return bool(norm(origin_sigungu)) and norm(origin_sigungu) == norm(destination_sigungu)


def training_round_trip_count(
    *,
    start_date: date,
    end_date: date | None,
    stay_mode: str,
    custom_round_trips: int | None,
) -> int:
    days = trip_days(start_date, end_date)
    if stay_mode == "residential":
        return 1
    if stay_mode == "nonresidential":
        return days
    if stay_mode == "custom":
        if custom_round_trips is None:
            raise ValueError("교육훈련 혼합형은 왕복 횟수를 입력해야 합니다.")
        if custom_round_trips < 1 or custom_round_trips > days:
            raise ValueError(f"교육훈련 왕복 횟수는 1~{days}회 사이여야 합니다.")
        return custom_round_trips
    raise ValueError("지원하지 않는 교육훈련 숙박 방식입니다.")


def transport_distance(
    *,
    one_way_km: float,
    start_date: date,
    end_date: date | None,
    trip_type: str,
    round_trip: bool,
    normal_stay_mode: str,
    training_stay_mode: str,
    training_round_trips: int | None,
) -> tuple[float, float]:
    if trip_type == "training":
        # 2026 교육훈련여비 지급기준: 근무지외 교육훈련 운임은
        # 합숙·비합숙 모두 여행구간 등급별 왕복운임 정액(왕복 1회).
        return round(one_way_km * 2, 1), 1.0

    days = trip_days(start_date, end_date)
    if not round_trip:
        return round(one_way_km, 1), 0.5

    # 일반출장도 실제 이동형태에 맞춰 계산합니다.
    # 숙박: 첫날 출발·마지막날 귀가로 전체 일정 왕복 1회.
    # 비숙박: 매일 출퇴근하므로 출장일수만큼 왕복.
    count = 1.0 if days > 1 and normal_stay_mode == "residential" else float(days)
    return round(one_way_km * 2 * count, 1), count


def _meal_allowance_by_count(days: int, claimed_meals: int) -> tuple[int, int]:
    max_meals = days * 3
    meals = min(max(claimed_meals, 0), max_meals)
    meal = MEAL_ALLOWANCE_RATE * Decimal(days)
    meal -= (MEAL_ALLOWANCE_RATE / Decimal("3")) * Decimal(meals)
    meal = max(Decimal("0"), meal)
    return _won(meal), meals


def calculate_allowances(
    *,
    start_date: date,
    end_date: date | None,
    trip_type: str,
    public_vehicle: bool,
    provided_meals_count: int,
    training_boarding: bool,
    training_stay_mode: str,
    training_round_trips: int | None,
    training_meal_claim_count: int,
    training_meal_claim_amount: int,
    origin_sigungu: str,
    destination_sigungu: str,
) -> dict:
    days = trip_days(start_date, end_date)
    in_work_area = same_work_area(origin_sigungu, destination_sigungu)

    if trip_type == "training":
        round_trips = 1

        middle_days = max(days - 2, 0)
        if days == 1:
            daily = DAILY_ALLOWANCE_RATE
        else:
            middle_half_days = 0 if training_boarding else middle_days
            daily = DAILY_ALLOWANCE_RATE * Decimal("2")
            daily += DAILY_ALLOWANCE_RATE * Decimal("0.5") * Decimal(middle_half_days)

        if public_vehicle:
            daily *= Decimal("0.5")

        if training_boarding:
            meal_claim_amount = max(int(training_meal_claim_amount or 0), 0)
            meal_allowance = meal_claim_amount
            meal_note = (
                f"합숙 · 교육훈련기관 식비 청구액 {meal_claim_amount:,}원"
                if meal_claim_amount
                else "합숙 · 교육훈련기관 식비 청구액 없음"
            )
        else:
            lunch_count = min(max(int(training_meal_claim_count or 0), 0), days)
            meal = MEAL_ALLOWANCE_RATE * Decimal(days)
            meal -= (MEAL_ALLOWANCE_RATE / Decimal("3")) * Decimal(lunch_count)
            meal = max(Decimal("0"), meal)
            meal_allowance = _won(meal)
            meal_note = (
                f"비합숙 · 25,000원 × {days}일 - 중식 제공 {lunch_count}회 × 1/3"
                if lunch_count
                else f"비합숙 · 25,000원 × {days}일 · 중식 제공 없음"
            )

        boarding_label = "합숙" if training_boarding else "비합숙"
        daily_note = f"{boarding_label} · 등록/수료일 전액"
        if days > 2:
            if training_boarding:
                daily_note += f" · 중간 {middle_days}일 일비 없음"
            else:
                daily_note += f" · 중간 {middle_days}일 50%"
        if public_vehicle:
            daily_note += " · 공용차량 50% 감액"

        return {
            "trip_days": days,
            "daily_allowance": _won(daily),
            "meal_allowance": meal_allowance,
            "training_scope": "근무지내" if in_work_area else "근무지외",
            "daily_note": daily_note,
            "meal_note": meal_note,
            "round_trip_count": round_trips,
        }

    daily = DAILY_ALLOWANCE_RATE * Decimal(days)
    if public_vehicle:
        daily *= Decimal("0.5")

    meal_allowance, meals = _meal_allowance_by_count(days, provided_meals_count)

    return {
        "trip_days": days,
        "daily_allowance": _won(daily),
        "meal_allowance": meal_allowance,
        "training_scope": None,
        "daily_note": "25,000원 × 일수" + (" × 50%(공용차량)" if public_vehicle else ""),
        "meal_note": f"25,000원 × {days}일 - 제공식사 {meals}식 × 1/3",
        "round_trip_count": None,
    }
