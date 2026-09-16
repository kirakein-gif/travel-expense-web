from datetime import date
from pydantic import BaseModel, Field
from typing import Literal, Optional
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
    energy_price: Optional[float] = None
    estimated_transport_cost: Optional[int] = None
    price_source: Optional[str] = None
    evidence_status: str = "pending"
