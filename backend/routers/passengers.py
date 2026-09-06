from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas

router = APIRouter()

@router.post("/", response_model=schemas.PassengerResponse, status_code=status.HTTP_201_CREATED)
def create_passenger(passenger: schemas.PassengerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Passenger).filter(models.Passenger.email == passenger.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    db_passenger = models.Passenger(**passenger.model_dump())
    db.add(db_passenger)
    db.commit()
    db.refresh(db_passenger)
    return db_passenger

@router.get("/", response_model=List[schemas.PassengerResponse])
def get_passengers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    passengers = db.query(models.Passenger).offset(skip).limit(limit).all()
    return passengers

@router.get("/{passenger_id}", response_model=schemas.PassengerResponse)
def get_passenger(passenger_id: int, db: Session = Depends(get_db)):
    passenger = db.query(models.Passenger).filter(models.Passenger.id == passenger_id).first()
    if not passenger:
        raise HTTPException(status_code=404, detail="Passenger not found")
    return passenger

@router.patch("/{passenger_id}", response_model=schemas.PassengerResponse)
def update_passenger(passenger_id: int, passenger_update: schemas.PassengerUpdate, db: Session = Depends(get_db)):
    passenger = db.query(models.Passenger).filter(models.Passenger.id == passenger_id).first()
    if not passenger:
        raise HTTPException(status_code=404, detail="Passenger not found")
    
    update_data = passenger_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(passenger, key, value)
        
    db.commit()
    db.refresh(passenger)
    return passenger
