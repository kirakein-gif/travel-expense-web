from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP


def _to_decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def truncate_to_tens(value: Decimal) -> int:
    """Discard the won digit (10원 미만 절사)."""
    return int((value / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_DOWN) * Decimal("10"))


def calculate_transport_cost(distance_km: float, efficiency: float, unit_price: float) -> int:
    """Legacy helper: calculate once and round to the nearest won."""
    amount = _to_decimal(distance_km) / _to_decimal(efficiency) * _to_decimal(unit_price)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_repeated_transport_cost(
    *,
    one_way_km: float,
    efficiency: float,
    unit_price: float,
    round_trip_count: float,
) -> tuple[int, int]:
    """Calculate one travel unit, truncate to 10-won units, then multiply.

    round_trip_count=1 means one round trip.
    round_trip_count=0.5 means one-way only.
    Training travel normally uses integer round-trip counts.
    """
    distance = _to_decimal(one_way_km)
    efficiency_d = _to_decimal(efficiency)
    price = _to_decimal(unit_price)

    if round_trip_count == 0.5:
        raw_unit = distance * price / efficiency_d
        unit_cost = truncate_to_tens(raw_unit)
        return unit_cost, unit_cost

    raw_round_trip = distance * Decimal("2") * price / efficiency_d
    unit_cost = truncate_to_tens(raw_round_trip)
    total = _to_decimal(unit_cost) * _to_decimal(round_trip_count)
    return unit_cost, int(total.quantize(Decimal("1"), rounding=ROUND_DOWN))
