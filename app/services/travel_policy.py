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


def calculate_allowances(
    *,
    start_date: date,
    end_date: date | None,
    trip_type: str,
    public_vehicle: bool,
    provided_meals_count: int,
    training_residential: bool,
    training_meal_claim_amount: int,
    origin_sigungu: str,
    destination_sigungu: str,
) -> dict:
    days = trip_days(start_date, end_date)
    in_work_area = same_work_area(origin_sigungu, destination_sigungu)

    if trip_type == "training":
        full_days = 1 if days == 1 else 2
        other_days = max(days - full_days, 0)
        daily = DAILY_ALLOWANCE_RATE * Decimal(full_days)
        if not training_residential:
            daily += DAILY_ALLOWANCE_RATE * Decimal("0.5") * Decimal(other_days)

        if public_vehicle:
            daily *= Decimal("0.5")

        claim = Decimal(str(max(training_meal_claim_amount, 0)))
        if training_residential:
            meal = claim
            meal_note = "합숙/기숙사: 교육훈련기관 청구액"
        elif in_work_area:
            if claim > 0:
                meal = claim
                meal_note = "근무지내 비합숙: 교육훈련기관 청구액"
            else:
                meal = (MEAL_ALLOWANCE_RATE / Decimal("3")) * Decimal(days)
                meal_note = "근무지내 비합숙: 식비의 1/3"
        else:
            standard = MEAL_ALLOWANCE_RATE * Decimal(days)
            if claim > 0:
                meal = max(Decimal("0"), standard - claim)
                meal_note = "근무지외 비합숙: 중식비 청구액 제외 차액"
            else:
                meal = standard
                meal_note = "근무지외 비합숙: 중식비 미청구 전액"

        return {
            "trip_days": days,
            "daily_allowance": _won(daily),
            "meal_allowance": _won(meal),
            "training_scope": "근무지내" if in_work_area else "근무지외",
            "daily_note": "등록·수료일 전액, 기타일 " + ("미지급" if training_residential else "50%") + (" · 공용차량 50% 감액" if public_vehicle else ""),
            "meal_note": meal_note,
        }

    daily = DAILY_ALLOWANCE_RATE * Decimal(days)
    if public_vehicle:
        daily *= Decimal("0.5")

    max_meals = days * 3
    meals = min(max(provided_meals_count, 0), max_meals)
    meal = MEAL_ALLOWANCE_RATE * Decimal(days)
    meal -= (MEAL_ALLOWANCE_RATE / Decimal("3")) * Decimal(meals)
    meal = max(Decimal("0"), meal)

    return {
        "trip_days": days,
        "daily_allowance": _won(daily),
        "meal_allowance": _won(meal),
        "training_scope": None,
        "daily_note": "25,000원 × 일수" + (" × 50%(공용차량)" if public_vehicle else ""),
        "meal_note": f"25,000원 × {days}일 - 제공식사 {meals}식 × 1/3",
    }
