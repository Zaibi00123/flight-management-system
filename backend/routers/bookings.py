from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
import models, schemas
from services.booking_service import process_booking, cancel_booking as cancel_booking_service

router = APIRouter()

@router.post("/", response_model=schemas.BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    booking: schemas.BookingCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    return process_booking(booking_in=booking, db=db, idempotency_key=idempotency_key)

@router.get("/{booking_id}", response_model=schemas.BookingResponse)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking

@router.post("/{booking_id}/cancel", response_model=schemas.CancellationResponse)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    return cancel_booking_service(booking_id=booking_id, db=db)
