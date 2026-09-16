from decimal import Decimal, ROUND_HALF_UP
def calculate_transport_cost(distance_km: float, efficiency: float, unit_price: float) -> int:
    amount = Decimal(str(distance_km)) / Decimal(str(efficiency)) * Decimal(str(unit_price))
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
