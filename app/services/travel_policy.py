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
    training_stay_mode: str,
    training_round_trips: int | None,
) -> tuple[float, float]:
    if trip_type == "training":
        count = training_round_trip_count(
            start_date=start_date,
            end_date=end_date,
            stay_mode=training_stay_mode,
            custom_round_trips=training_round_trips,
        )
        return round(one_way_km * 2 * count, 1), float(count)

    count = 1.0 if round_trip else 0.5
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
    training_stay_mode: str,
    training_round_trips: int | None,
    training_meal_claim_count: int,
    origin_sigungu: str,
    destination_sigungu: str,
) -> dict:
    days = trip_days(start_date, end_date)
    in_work_area = same_work_area(origin_sigungu, destination_sigungu)

    if trip_type == "training":
        round_trips = training_round_trip_count(
            start_date=start_date,
            end_date=end_date,
            stay_mode=training_stay_mode,
            custom_round_trips=training_round_trips,
        )

        if days == 1:
            daily = DAILY_ALLOWANCE_RATE
            middle_nonresidential = 0
        else:
            middle_days = max(days - 2, 0)
            if training_stay_mode == "nonresidential":
                middle_nonresidential = middle_days
            elif training_stay_mode == "residential":
                middle_nonresidential = 0
            else:
                middle_nonresidential = min(max(round_trips - 1, 0), middle_days)
            daily = DAILY_ALLOWANCE_RATE * Decimal("2")
            daily += DAILY_ALLOWANCE_RATE * Decimal("0.5") * Decimal(middle_nonresidential)

        if public_vehicle:
            daily *= Decimal("0.5")

        meal_allowance, meal_count = _meal_allowance_by_count(days, training_meal_claim_count)
        meal_note = (
            f"25,000원 × {days}일 - 교육훈련기관 식비 청구 {meal_count}식 × 1/3"
            if meal_count
            else f"25,000원 × {days}일 · 교육훈련기관 식비 청구 없음"
        )

        stay_label = {
            "nonresidential": "전일 비숙박",
            "residential": "전일 숙박",
            "custom": "혼합",
        }[training_stay_mode]
        daily_note = f"{stay_label} · 등록/수료일 전액"
        if days > 2:
            daily_note += f" · 중간 비숙박 {middle_nonresidential}일 50%"
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
