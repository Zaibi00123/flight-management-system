from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas

router = APIRouter()

@router.post("/", response_model=schemas.FlightResponse, status_code=status.HTTP_201_CREATED)
def create_flight(flight: schemas.FlightCreate, db: Session = Depends(get_db)):
    if flight.total_seats != (flight.first_seats + flight.business_seats + flight.economy_seats):
        raise HTTPException(status_code=400, detail="Total seats must equal the sum of class seats")
    
    if flight.first_seats < 0 or flight.business_seats < 0 or flight.economy_seats < 0:
        raise HTTPException(status_code=400, detail="Seat counts cannot be negative")

    if flight.arrival_time <= flight.departure_time:
        raise HTTPException(status_code=400, detail="Arrival time must be after departure time")

    db_flight = models.Flight(
        **flight.model_dump(),
        available_first=flight.first_seats,
        available_business=flight.business_seats,
        available_economy=flight.economy_seats
    )
    db.add(db_flight)
    db.commit()
    db.refresh(db_flight)
    return db_flight

@router.get("/", response_model=List[schemas.FlightResponse])
def get_flights(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    flights = db.query(models.Flight).offset(skip).limit(limit).all()
    return flights

@router.get("/{flight_id}", response_model=schemas.FlightResponse)
def get_flight(flight_id: int, db: Session = Depends(get_db)):
    flight = db.query(models.Flight).filter(models.Flight.id == flight_id).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    return flight

@router.patch("/{flight_id}", response_model=schemas.FlightResponse)
def update_flight(flight_id: int, flight_update: schemas.FlightUpdate, db: Session = Depends(get_db)):
    flight = db.query(models.Flight).filter(models.Flight.id == flight_id).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    
    update_data = flight_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(flight, key, value)
        
    db.commit()
    db.refresh(flight)
    return flight
