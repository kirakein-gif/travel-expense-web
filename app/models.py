from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

VehicleType = Literal[
    "gasoline", "diesel", "lpg", "hybrid", "phev", "electric", "hydrogen"
]
PhevEnergySource = Literal["gasoline", "electric"]
TripType = Literal["normal", "training"]
TrainingStayMode = Literal["nonresidential", "residential", "custom"]


class TravelRequest(BaseModel):
    travel_date: date
    end_date: Optional[date] = None
    origin: str = Field(min_length=2)
    destination: str = Field(min_length=2)
    vehicle_type: VehicleType
    phev_energy_source: Optional[PhevEnergySource] = None
    efficiency: Optional[float] = Field(default=None, gt=0)
    manual_energy_price: Optional[float] = Field(default=None, gt=0)
    round_trip: bool = True

    trip_type: TripType = "normal"
    public_vehicle: bool = False
    provided_meals_count: int = Field(default=0, ge=0)
    training_stay_mode: TrainingStayMode = "nonresidential"
    training_round_trips: Optional[int] = Field(default=None, ge=1)
    training_meal_claim_count: int = Field(default=0, ge=0)

    toll_fee: int = Field(default=0, ge=0)
    parking_fee: int = Field(default=0, ge=0)
    lodging_fee: int = Field(default=0, ge=0)

    affiliation: Optional[str] = None
    position: Optional[str] = None
    traveler_name: Optional[str] = None
    passengers: Optional[str] = None
    purpose: Optional[str] = None


class DistanceResponse(BaseModel):
    one_way_distance_km: float
    distance_km: float
    distance_source: str
    destination_code: Optional[str] = None
    origin_support_office: Optional[str] = None
    destination_support_office: Optional[str] = None
    distance_cache_hit: bool = False
    province: str
    sigungu: str
    origin_province: str = ""
    origin_sigungu: str = ""
    resolved_origin_name: Optional[str] = None
    resolved_origin_address: Optional[str] = None
    resolved_destination_name: Optional[str] = None
    resolved_destination_address: Optional[str] = None


class PriceRequest(BaseModel):
    travel_date: date
    end_date: Optional[date] = None
    vehicle_type: VehicleType
    phev_energy_source: Optional[PhevEnergySource] = None
    efficiency: Optional[float] = Field(default=None, gt=0)
    manual_energy_price: Optional[float] = Field(default=None, gt=0)
    distance_km: float = Field(gt=0)
    one_way_distance_km: Optional[float] = Field(default=None, gt=0)
    round_trip: bool = True
    province: str = Field(min_length=1)
    sigungu: str = Field(min_length=1)
    origin_sigungu: str = ""

    trip_type: TripType = "normal"
    public_vehicle: bool = False
    provided_meals_count: int = Field(default=0, ge=0)
    training_stay_mode: TrainingStayMode = "nonresidential"
    training_round_trips: Optional[int] = Field(default=None, ge=1)
    training_meal_claim_count: int = Field(default=0, ge=0)

    toll_fee: int = Field(default=0, ge=0)
    parking_fee: int = Field(default=0, ge=0)
    lodging_fee: int = Field(default=0, ge=0)


class PriceResponse(BaseModel):
    energy_price: Optional[float] = None
    estimated_transport_cost: Optional[int] = None
    price_source: Optional[str] = None
    price_cache_hit: bool = False
    evidence_status: str = "pending"
    fuel_price_date: Optional[date] = None

    vehicle_label: Optional[str] = None
    effective_efficiency: Optional[float] = None
    efficiency_unit: Optional[str] = None
    calculation_formula: Optional[str] = None
    transport_unit_cost: Optional[int] = None
    transport_distance_km: float = 0
    round_trip_count: float = 0

    trip_days: int = 1
    daily_allowance: int = 0
    meal_allowance: int = 0
    toll_fee: int = 0
    parking_fee: int = 0
    lodging_fee: int = 0
    total_expense: Optional[int] = None
    training_scope: Optional[str] = None
    daily_note: Optional[str] = None
    meal_note: Optional[str] = None


class EvidenceRequest(BaseModel):
    travel_date: date
    vehicle_type: Literal["gasoline", "diesel", "lpg"]
    province: str = Field(min_length=1)
    sigungu: str = Field(min_length=1)
    expected_price: float = Field(gt=0)


class EstimateResponse(DistanceResponse, PriceResponse):
    pass
