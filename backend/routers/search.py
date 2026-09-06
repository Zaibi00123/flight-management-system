from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone
from database import get_db
import models, schemas
import uuid

router = APIRouter()

def ensure_default_fare_rules(db: Session):
    existing = db.query(models.FareRule).first()
    if not existing:
        default_rules = [
            models.FareRule(
                fare_type="BASIC_ECONOMY",
                seat_class="ECONOMY",
                change_allowed=False,
                refundable=False,
                credit_allowed=False,
                cancellation_fee=100.0,
                rules_text="Non-refundable, no changes permitted, no advance seat selection."
            ),
            models.FareRule(
                fare_type="FLEXIBLE",
                seat_class="ECONOMY",
                change_allowed=True,
                refundable=True,
                credit_allowed=True,
                cancellation_fee=0.0,
                rules_text="Fully refundable, free changes permitted up to 24h before departure."
            ),
            models.FareRule(
                fare_type="STANDARD",
                seat_class="ECONOMY",
                change_allowed=True,
                refundable=False,
                credit_allowed=True,
                cancellation_fee=50.0,
                rules_text="Standard fare. Changes permitted with fee, non-refundable."
            )
        ]
        db.add_all(default_rules)
        db.commit()

@router.get("/flights", response_model=List[schemas.FlightSearchResult])
def search_flights(
    origin: str = Query(..., description="3-letter airport code or city"),
    destination: str = Query(..., description="3-letter airport code or city"),
    departure_date: Optional[str] = Query(None, description="Departure date in YYYY-MM-DD format"),
    seat_class: Optional[models.SeatClass] = Query(None, description="FIRST, BUSINESS, or ECONOMY"),
    passengers: int = Query(1, ge=1, description="Number of passengers"),
    db: Session = Depends(get_db)
):
    # Route validation
    if not origin or not origin.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origin airport code is required")
    if not destination or not destination.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Destination airport code is required")
    
    if origin.strip().upper() == destination.strip().upper():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origin and destination cannot be identical")

    # Date validation
    date_filter = None
    if departure_date:
        try:
            date_filter = datetime.strptime(departure_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid departure_date format. Please use YYYY-MM-DD format."
            )

    # Base query
    query = db.query(models.Flight).filter(
        func.upper(models.Flight.origin) == origin.strip().upper(),
        func.upper(models.Flight.destination) == destination.strip().upper()
    )

    if date_filter:
        query = query.filter(func.date(models.Flight.departure_time) == date_filter)

    flights = query.all()

    # Filter by inventory & seat class
    results = []
    ensure_default_fare_rules(db)
    all_fare_rules = db.query(models.FareRule).all()
    fare_responses = [schemas.FareRuleResponse.model_validate(fr) for fr in all_fare_rules]

    for fl in flights:
        has_seats = False
        if seat_class == models.SeatClass.FIRST and fl.available_first >= passengers:
            has_seats = True
        elif seat_class == models.SeatClass.BUSINESS and fl.available_business >= passengers:
            has_seats = True
        elif seat_class == models.SeatClass.ECONOMY and fl.available_economy >= passengers:
            has_seats = True
        elif seat_class is None:
            if (fl.available_first >= passengers or 
                fl.available_business >= passengers or 
                fl.available_economy >= passengers):
                has_seats = True

        if has_seats:
            result_item = schemas.FlightSearchResult(
                id=fl.id,
                flight_number=fl.flight_number,
                origin=fl.origin,
                destination=fl.destination,
                departure_time=fl.departure_time,
                arrival_time=fl.arrival_time,
                total_seats=fl.total_seats,
                first_seats=fl.first_seats,
                business_seats=fl.business_seats,
                economy_seats=fl.economy_seats,
                available_first=fl.available_first,
                available_business=fl.available_business,
                available_economy=fl.available_economy,
                status=fl.status,
                created_at=fl.created_at,
                updated_at=fl.updated_at,
                applicable_fares=fare_responses
            )
            results.append(result_item)

    return results

@router.get("/fare-rules", response_model=List[schemas.FareRuleResponse])
def get_fare_rules(db: Session = Depends(get_db)):
    ensure_default_fare_rules(db)
    return db.query(models.FareRule).all()

@router.post("/price-hold", response_model=schemas.PriceHoldResponse, status_code=status.HTTP_201_CREATED)
def create_price_hold(hold_in: schemas.PriceHoldCreate, db: Session = Depends(get_db)):
    flight = db.query(models.Flight).filter(models.Flight.id == hold_in.flight_id).first()
    if not flight:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flight not found")

    hold_ref = f"HOLD-{str(uuid.uuid4())[:8].upper()}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=hold_in.duration_minutes)

    price_hold = models.PriceHold(
        hold_reference=hold_ref,
        flight_id=hold_in.flight_id,
        fare_type=hold_in.fare_type.upper(),
        seat_class=hold_in.seat_class.value if isinstance(hold_in.seat_class, models.SeatClass) else hold_in.seat_class,
        held_price=hold_in.held_price,
        expires_at=expires_at
    )
    db.add(price_hold)
    db.commit()
    db.refresh(price_hold)
    return price_hold
