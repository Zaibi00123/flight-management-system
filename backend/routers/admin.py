from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timezone
from database import get_db
import models, schemas

router = APIRouter()

def get_admin_role(x_admin_role: Optional[str] = Header(None, alias="X-Admin-Role")) -> str:
    if not x_admin_role or x_admin_role.strip().lower() not in ["super-admin", "ops-agent"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or unauthorized admin role header. Expected 'super-admin' or 'ops-agent'."
        )
    return x_admin_role.strip().lower()

@router.post("/flights", response_model=schemas.AdminFlightResponse, status_code=status.HTTP_201_CREATED)
def create_flight_admin(
    flight_in: schemas.AdminFlightCreate,
    admin_role: str = Depends(get_admin_role),
    db: Session = Depends(get_db)
):
    # 1. Validate Seat Allocation Sum
    if flight_in.first_seats + flight_in.business_seats + flight_in.economy_seats != flight_in.total_seats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total seats ({flight_in.total_seats}) must equal the sum of class seats ({flight_in.first_seats + flight_in.business_seats + flight_in.economy_seats})."
        )

    # 2. Validate Positive Seat Allocations
    if flight_in.first_seats < 0 or flight_in.business_seats < 0 or flight_in.economy_seats < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat allocation counts cannot be negative."
        )

    # 3. Validate Date Order
    if flight_in.arrival_time <= flight_in.departure_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arrival time must be strictly after departure time."
        )

    # 4. Validate Route
    if flight_in.origin.strip().upper() == flight_in.destination.strip().upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination cannot be identical."
        )

    # 5. Check Duplicate Flight Number on Same Date & Route
    dep_date = flight_in.departure_time.date() if isinstance(flight_in.departure_time, datetime) else flight_in.departure_time
    existing_duplicate = db.query(models.Flight).filter(
        func.upper(models.Flight.flight_number) == flight_in.flight_number.strip().upper(),
        func.upper(models.Flight.origin) == flight_in.origin.strip().upper(),
        func.date(models.Flight.departure_time) == dep_date
    ).first()

    if existing_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Flight '{flight_in.flight_number.upper()}' already exists for route {flight_in.origin.upper()} on date {dep_date}."
        )

    # 6. Insert Flight & AuditLog
    try:
        db_flight = models.Flight(
            flight_number=flight_in.flight_number.strip().upper(),
            origin=flight_in.origin.strip().upper(),
            destination=flight_in.destination.strip().upper(),
            departure_time=flight_in.departure_time,
            arrival_time=flight_in.arrival_time,
            total_seats=flight_in.total_seats,
            first_seats=flight_in.first_seats,
            business_seats=flight_in.business_seats,
            economy_seats=flight_in.economy_seats,
            available_first=flight_in.first_seats,
            available_business=flight_in.business_seats,
            available_economy=flight_in.economy_seats,
            status=models.FlightStatus.SCHEDULED
        )
        db.add(db_flight)
        db.flush()

        audit = models.AuditLog(
            entity_type="FLIGHT",
            entity_id=db_flight.id,
            action="CREATE_FLIGHT",
            actor=admin_role,
            details=f"Admin ({admin_role}) created flight {db_flight.flight_number} ({db_flight.origin}->{db_flight.destination}) with {db_flight.total_seats} total seats."
        )
        db.add(audit)

        db.commit()
        db.refresh(db_flight)

        resp = schemas.AdminFlightResponse.model_validate(db_flight)
        resp.active_bookings_affected = False
        return resp

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create flight: {str(e)}"
        )

@router.patch("/flights/{flight_id}", response_model=schemas.AdminFlightResponse)
def edit_flight_admin(
    flight_id: int,
    flight_update: schemas.AdminFlightUpdate,
    admin_role: str = Depends(get_admin_role),
    db: Session = Depends(get_db)
):
    # 1. Fetch Flight
    flight = db.query(models.Flight).filter(models.Flight.id == flight_id).first()
    if not flight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Flight not found"
        )

    # 2. Check Active Bookings
    active_bookings_count = db.query(models.Booking).filter(
        models.Booking.flight_id == flight_id,
        ~models.Booking.status.startswith("CANCELLED")
    ).count()
    active_affected = (active_bookings_count > 0)

    # 3. Role Restriction Check for ops-agent
    now_utc = datetime.now(timezone.utc)
    dep_time = flight.departure_time
    if dep_time.tzinfo is None:
        dep_time = dep_time.replace(tzinfo=timezone.utc)

    if admin_role == "ops-agent":
        if active_affected or dep_time <= now_utc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ops-agent role is not authorized to edit flights with active bookings or already-departed flights. Requires super-admin."
            )

    # 4. Shrink Protection Check
    booked_first = flight.first_seats - flight.available_first
    booked_business = flight.business_seats - flight.available_business
    booked_economy = flight.economy_seats - flight.available_economy

    if flight_update.first_seats is not None and flight_update.first_seats < booked_first:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reduce FIRST seats to {flight_update.first_seats}. Already booked: {booked_first}."
        )

    if flight_update.business_seats is not None and flight_update.business_seats < booked_business:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reduce BUSINESS seats to {flight_update.business_seats}. Already booked: {booked_business}."
        )

    if flight_update.economy_seats is not None and flight_update.economy_seats < booked_economy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reduce ECONOMY seats to {flight_update.economy_seats}. Already booked: {booked_economy}."
        )

    # 5. Apply Updates & Recalculate Seat Inventory
    old_summary = f"origin={flight.origin}, dest={flight.destination}, dep={flight.departure_time}, arr={flight.arrival_time}, total={flight.total_seats}"
    
    if flight_update.origin is not None:
        flight.origin = flight_update.origin.strip().upper()
    if flight_update.destination is not None:
        flight.destination = flight_update.destination.strip().upper()

    if flight.origin == flight.destination:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination cannot be identical."
        )

    schedule_override_applied = False
    flagged_count = 0
    if flight_update.departure_time is not None and flight.departure_time is not None:
        old_dep_dt = flight.departure_time if flight.departure_time.tzinfo else flight.departure_time.replace(tzinfo=timezone.utc)
        new_dep_dt = flight_update.departure_time if flight_update.departure_time.tzinfo else flight_update.departure_time.replace(tzinfo=timezone.utc)
        diff_seconds = abs((new_dep_dt - old_dep_dt).total_seconds())

        if diff_seconds >= 3600: # Threshold >= 60 minutes (3600 seconds)
            schedule_override_applied = True
            active_bookings = db.query(models.Booking).filter(
                models.Booking.flight_id == flight_id,
                ~models.Booking.status.startswith("CANCELLED")
            ).all()

            for b in active_bookings:
                b.schedule_change_override = True
            flagged_count = len(active_bookings)

        flight.departure_time = flight_update.departure_time

    if flight_update.arrival_time is not None:
        flight.arrival_time = flight_update.arrival_time

    if flight.arrival_time <= flight.departure_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arrival time must be strictly after departure time."
        )

    if flight_update.first_seats is not None:
        delta = flight_update.first_seats - flight.first_seats
        flight.first_seats = flight_update.first_seats
        flight.available_first += delta

    if flight_update.business_seats is not None:
        delta = flight_update.business_seats - flight.business_seats
        flight.business_seats = flight_update.business_seats
        flight.available_business += delta

    if flight_update.economy_seats is not None:
        delta = flight_update.economy_seats - flight.economy_seats
        flight.economy_seats = flight_update.economy_seats
        flight.available_economy += delta

    flight.total_seats = flight.first_seats + flight.business_seats + flight.economy_seats

    if flight_update.status is not None:
        flight.status = flight_update.status.value if hasattr(flight_update.status, "value") else str(flight_update.status)

    new_summary = f"origin={flight.origin}, dest={flight.destination}, dep={flight.departure_time}, arr={flight.arrival_time}, total={flight.total_seats}"

    # 6. AuditLog Recording
    audit_details = f"Admin ({admin_role}) edited flight {flight.flight_number}. Before: [{old_summary}] -> After: [{new_summary}]. Active bookings affected: {active_affected}."
    if schedule_override_applied:
        audit_details += f" Schedule change exceeded 60m threshold. Flagged {flagged_count} bookings with schedule_change_override."

    audit = models.AuditLog(
        entity_type="FLIGHT",
        entity_id=flight.id,
        action="EDIT_FLIGHT",
        actor=admin_role,
        details=audit_details
    )
    db.add(audit)

    db.commit()
    db.refresh(flight)

    resp = schemas.AdminFlightResponse.model_validate(flight)
    resp.active_bookings_affected = active_affected
    return resp

@router.post("/flights/{flight_id}/cancel", response_model=schemas.AdminFlightCancelResponse)
def cancel_flight_admin(
    flight_id: int,
    admin_role: str = Depends(get_admin_role),
    db: Session = Depends(get_db)
):
    # 1. Role Restriction: Only super-admin can cancel an entire flight
    if admin_role != "super-admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super-admin role is authorized to cancel an entire flight. ops-agent role is restricted."
        )

    try:
        # 2. Row Lock & Fetch Flight inside Transaction
        flight = db.query(models.Flight).with_for_update().filter(
            models.Flight.id == flight_id
        ).first()

        if not flight:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Flight not found"
            )

        if flight.status == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Flight '{flight.flight_number}' is already cancelled."
            )

        # 3. Update Flight Status
        flight.status = "CANCELLED"

        # 4. Cascade to Active Bookings (Airline-Initiated Override -> CANCELLED_REFUNDED)
        active_bookings = db.query(models.Booking).filter(
            models.Booking.flight_id == flight_id,
            ~models.Booking.status.startswith("CANCELLED")
        ).all()

        cascaded_count = len(active_bookings)
        for b in active_bookings:
            b.status = "CANCELLED_REFUNDED"

        # 5. Write Single Summary AuditLog Record
        audit = models.AuditLog(
            entity_type="FLIGHT",
            entity_id=flight.id,
            action="CANCEL_FLIGHT_CASCADE",
            actor=admin_role,
            details=f"Admin ({admin_role}) cancelled entire flight {flight.flight_number} (ID: {flight.id}). Cascaded {cascaded_count} active bookings to CANCELLED_REFUNDED."
        )
        db.add(audit)

        db.commit()

        return schemas.AdminFlightCancelResponse(
            flight_id=flight.id,
            status="CANCELLED",
            cascaded_bookings_count=cascaded_count,
            message=f"Flight {flight.flight_number} successfully cancelled. Cascaded {cascaded_count} active bookings to full refund status."
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Flight cancellation cascade failed: {str(e)}"
        )

@router.get("/audit-logs")
def get_admin_audit_logs(
    limit: int = 50,
    admin_role: str = Depends(get_admin_role),
    db: Session = Depends(get_db)
):
    logs = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "action": l.action,
            "actor": l.actor,
            "details": l.details,
            "created_at": l.created_at.isoformat() if l.created_at else None
        }
        for l in logs
    ]

