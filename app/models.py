from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

VehicleType = Literal["gasoline", "diesel", "lpg", "electric", "hydrogen"]


class TravelRequest(BaseModel):
    travel_date: date
    origin: str = Field(min_length=2)
    destination: str = Field(min_length=2)
    vehicle_type: VehicleType
    efficiency: float = Field(gt=0, description="km/L, km/kWh, or km/kg")
    round_trip: bool = True


class EstimateResponse(BaseModel):
    distance_km: float
    distance_source: str
    destination_code: Optional[str] = None
    origin_support_office: Optional[str] = None
    destination_support_office: Optional[str] = None
    distance_cache_hit: bool = False
    energy_price: Optional[float] = None
    estimated_transport_cost: Optional[int] = None
    price_source: Optional[str] = None
    price_cache_hit: bool = False
    evidence_status: str = "pending"
