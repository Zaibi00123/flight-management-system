from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from models import FlightStatus, SeatClass, BookingStatus

# --- FLIGHT SCHEMAS ---
class FlightBase(BaseModel):
    flight_number: str = Field(..., json_schema_extra={"example": "FL123"})
    origin: str = Field(..., json_schema_extra={"example": "JFK"})
    destination: str = Field(..., json_schema_extra={"example": "LHR"})
    departure_time: datetime
    arrival_time: datetime
    total_seats: int
    first_seats: int = 0
    business_seats: int = 0
    economy_seats: int = 0
    status: FlightStatus = FlightStatus.SCHEDULED

class FlightCreate(FlightBase):
    pass

class FlightUpdate(BaseModel):
    status: Optional[FlightStatus] = None
    departure_time: Optional[datetime] = None
    arrival_time: Optional[datetime] = None

class FlightResponse(FlightBase):
    id: int
    available_first: int
    available_business: int
    available_economy: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# --- PASSENGER SCHEMAS ---
class PassengerBase(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "John Doe"})
    email: EmailStr = Field(..., json_schema_extra={"example": "john@example.com"})
    phone: Optional[str] = None

class PassengerCreate(PassengerBase):
    pass

class PassengerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

class PassengerResponse(PassengerBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- FARE RULE SCHEMAS ---
class FareRuleResponse(BaseModel):
    id: int
    fare_type: str
    seat_class: str
    change_allowed: bool
    refundable: bool
    credit_allowed: bool
    cancellation_fee: float
    rules_text: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# --- PRICE HOLD SCHEMAS ---
class PriceHoldCreate(BaseModel):
    flight_id: int
    fare_type: str = Field(..., json_schema_extra={"example": "STANDARD"})
    seat_class: SeatClass
    held_price: float = Field(..., gt=0)
    duration_minutes: int = Field(15, gt=0, le=120)

class PriceHoldResponse(BaseModel):
    id: int
    hold_reference: str
    flight_id: int
    fare_type: str
    seat_class: str
    held_price: float
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- FLIGHT SEARCH SCHEMAS ---
class FlightSearchResult(FlightResponse):
    applicable_fares: List[FareRuleResponse] = []

# --- BOOKING SCHEMAS ---
class BookingBase(BaseModel):
    flight_id: int
    passenger_id: int
    fare_type: str = Field(..., json_schema_extra={"example": "STANDARD"})
    seat_class: SeatClass
    seats: int = Field(..., gt=0, json_schema_extra={"example": 1})
    amount: float = Field(..., gt=0)

class BookingCreate(BookingBase):
    hold_reference: Optional[str] = None
    idempotency_key: Optional[str] = None

class BookingResponse(BookingBase):
    id: int
    booking_reference: str
    status: str
    schedule_change_override: bool = False
    hold_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# --- CANCELLATION & WAITLIST SCHEMAS ---
class CancellationResponse(BaseModel):
    booking_id: int
    booking_reference: str
    status: str
    seats_restored: int
    fare_type: str
    message: str

class WaitlistCreate(BaseModel):
    flight_id: int
    passenger_id: int
    seat_class: SeatClass
    priority: int = Field(1, ge=1)

class WaitlistResponse(BaseModel):
    id: int
    flight_id: int
    passenger_id: int
    seat_class: str
    priority: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- ADMIN FLIGHT SCHEMAS ---
class AdminFlightCreate(BaseModel):
    flight_number: str = Field(..., json_schema_extra={"example": "PK-501"})
    origin: str = Field(..., json_schema_extra={"example": "LHE"})
    destination: str = Field(..., json_schema_extra={"example": "ISB"})
    departure_time: datetime
    arrival_time: datetime
    total_seats: int = Field(..., gt=0)
    first_seats: int = Field(0, ge=0)
    business_seats: int = Field(0, ge=0)
    economy_seats: int = Field(0, ge=0)

class AdminFlightUpdate(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[datetime] = None
    arrival_time: Optional[datetime] = None
    first_seats: Optional[int] = Field(None, ge=0)
    business_seats: Optional[int] = Field(None, ge=0)
    economy_seats: Optional[int] = Field(None, ge=0)
    status: Optional[FlightStatus] = None

class AdminFlightResponse(FlightResponse):
    active_bookings_affected: bool = False

class AdminFlightCancelResponse(BaseModel):
    flight_id: int
    status: str
    cascaded_bookings_count: int
    message: str
