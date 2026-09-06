from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Enum, CheckConstraint, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class FlightStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

class SeatClass(str, enum.Enum):
    FIRST = "FIRST"
    BUSINESS = "BUSINESS"
    ECONOMY = "ECONOMY"

class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

class Flight(Base):
    __tablename__ = "flights"
    id = Column(Integer, primary_key=True, index=True)
    flight_number = Column(String, index=True, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    departure_time = Column(DateTime(timezone=True), index=True, nullable=False)
    arrival_time = Column(DateTime(timezone=True), nullable=False)
    total_seats = Column(Integer, nullable=False)
    first_seats = Column(Integer, nullable=False, default=0)
    business_seats = Column(Integer, nullable=False, default=0)
    economy_seats = Column(Integer, nullable=False, default=0)
    available_first = Column(Integer, nullable=False)
    available_business = Column(Integer, nullable=False)
    available_economy = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default=FlightStatus.SCHEDULED)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint('total_seats = first_seats + business_seats + economy_seats', name='check_total_seats'),
        CheckConstraint('available_first >= 0', name='check_avail_first'),
        CheckConstraint('available_business >= 0', name='check_avail_bus'),
        CheckConstraint('available_economy >= 0', name='check_avail_econ'),
    )

class Passenger(Base):
    __tablename__ = "passengers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    booking_reference = Column(String, unique=True, index=True, nullable=False)
    flight_id = Column(Integer, ForeignKey("flights.id"), index=True, nullable=False)
    passenger_id = Column(Integer, ForeignKey("passengers.id"), index=True, nullable=False)
    fare_type = Column(String, nullable=False)
    seat_class = Column(String, nullable=False)
    seats = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, index=True, nullable=False, default=BookingStatus.PENDING)
    schedule_change_override = Column(Boolean, nullable=False, default=False)
    hold_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    flight = relationship("Flight")
    passenger = relationship("Passenger")

class Waitlist(Base):
    __tablename__ = "waitlist"
    id = Column(Integer, primary_key=True, index=True)
    flight_id = Column(Integer, ForeignKey("flights.id"), index=True, nullable=False)
    passenger_id = Column(Integer, ForeignKey("passengers.id"), index=True, nullable=False)
    seat_class = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=1)
    status = Column(String, index=True, nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FareRule(Base):
    __tablename__ = "fare_rules"
    id = Column(Integer, primary_key=True, index=True)
    fare_type = Column(String, nullable=False)
    seat_class = Column(String, nullable=False)
    change_allowed = Column(Boolean, nullable=False, default=False)
    refundable = Column(Boolean, nullable=False, default=False)
    credit_allowed = Column(Boolean, nullable=False, default=False)
    cancellation_fee = Column(Float, nullable=False, default=0.0)
    rules_text = Column(Text, nullable=True)

class Refund(Base):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, index=True, nullable=False, default="PENDING")
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, index=True, nullable=False)
    entity_id = Column(Integer, index=True, nullable=False)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FraudScore(Base):
    __tablename__ = "fraud_scores"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=False)
    score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PriceHold(Base):
    __tablename__ = "price_holds"
    id = Column(Integer, primary_key=True, index=True)
    hold_reference = Column(String, unique=True, index=True, nullable=False)
    flight_id = Column(Integer, ForeignKey("flights.id"), index=True, nullable=False)
    fare_type = Column(String, nullable=False)
    seat_class = Column(String, nullable=False)
    held_price = Column(Float, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    flight = relationship("Flight")

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String, unique=True, index=True, nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
