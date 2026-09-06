from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas

router = APIRouter()

@router.post("/", response_model=schemas.WaitlistResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(waitlist_in: schemas.WaitlistCreate, db: Session = Depends(get_db)):
    # 1. Check Passenger Exists
    passenger = db.query(models.Passenger).filter(models.Passenger.id == waitlist_in.passenger_id).first()
    if not passenger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passenger not found"
        )

    # 2. Check Flight Exists
    flight = db.query(models.Flight).filter(models.Flight.id == waitlist_in.flight_id).first()
    if not flight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Flight not found"
        )

    # 3. Check Seat Availability for Class
    seat_cls = waitlist_in.seat_class.value if isinstance(waitlist_in.seat_class, models.SeatClass) else str(waitlist_in.seat_class).upper()
    
    avail = 0
    if seat_cls == "FIRST":
        avail = flight.available_first
    elif seat_cls == "BUSINESS":
        avail = flight.available_business
    elif seat_cls == "ECONOMY":
        avail = flight.available_economy
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid seat class: '{seat_cls}'"
        )

    if avail > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seats are still available ({avail} remaining) for {seat_cls} class. Please create a booking directly instead of joining the waitlist."
        )

    # 4. Create Waitlist Entry & AuditLog inside Transaction
    try:
        db_waitlist = models.Waitlist(
            flight_id=waitlist_in.flight_id,
            passenger_id=waitlist_in.passenger_id,
            seat_class=seat_cls,
            priority=waitlist_in.priority,
            status="PENDING"
        )
        db.add(db_waitlist)
        db.flush()

        audit = models.AuditLog(
            entity_type="WAITLIST",
            entity_id=db_waitlist.id,
            action="JOIN_WAITLIST",
            actor="PASSENGER",
            details=f"Passenger {passenger.name} (ID: {passenger.id}) joined waitlist for flight {flight.flight_number} (ID: {flight.id}) class {seat_cls} with priority {waitlist_in.priority}."
        )
        db.add(audit)

        db.commit()
        db.refresh(db_waitlist)
        return db_waitlist

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join waitlist: {str(e)}"
        )

@router.get("/{flight_id}", response_model=List[schemas.WaitlistResponse])
def get_flight_waitlist(flight_id: int, db: Session = Depends(get_db)):
    flight = db.query(models.Flight).filter(models.Flight.id == flight_id).first()
    if not flight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Flight not found"
        )

    waitlist_entries = db.query(models.Waitlist).filter(
        models.Waitlist.flight_id == flight_id
    ).order_by(
        models.Waitlist.priority.asc(),
        models.Waitlist.created_at.asc()
    ).all()

    return waitlist_entries
