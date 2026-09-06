from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import models, schemas
import uuid
import json
from datetime import datetime, timezone

def process_booking(
    booking_in: schemas.BookingCreate,
    db: Session,
    idempotency_key: str = None
) -> models.Booking:
    # Resolve effective idempotency key (header overrides or uses payload field)
    key = idempotency_key or booking_in.idempotency_key

    # 1. Idempotency Check
    if key:
        existing_record = db.query(models.IdempotencyRecord).filter(
            models.IdempotencyRecord.idempotency_key == key
        ).first()
        if existing_record:
            # Return cached booking result if found
            if existing_record.booking_id:
                booking = db.query(models.Booking).filter(
                    models.Booking.id == existing_record.booking_id
                ).first()
                if booking:
                    return booking
            try:
                data = json.loads(existing_record.response_json)
                return data
            except Exception:
                pass

    # 2. Fare Type Validation
    valid_fare_types = ["BASIC_ECONOMY", "FLEXIBLE", "STANDARD"]
    db_fare_types = [f.fare_type for f in db.query(models.FareRule).all()]
    all_fare_types = list(set(valid_fare_types + db_fare_types))
    
    if booking_in.fare_type.upper() not in [ft.upper() for ft in all_fare_types]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unsupported fare type: '{booking_in.fare_type}'"
        )

    # 3. Price Hold Validation
    if booking_in.hold_reference:
        price_hold = db.query(models.PriceHold).filter(
            models.PriceHold.hold_reference == booking_in.hold_reference
        ).first()
        if not price_hold:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid price hold reference"
            )
        
        now_utc = datetime.now(timezone.utc)
        expires_at = price_hold.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            
        if expires_at < now_utc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Price hold has expired. Please re-query current flight prices."
            )

    # 4. Quantity & Passenger Check
    if booking_in.seats <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat quantity must be a positive integer"
        )

    passenger = db.query(models.Passenger).filter(
        models.Passenger.id == booking_in.passenger_id
    ).first()
    if not passenger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passenger not found"
        )

    # 5. Row Locking & Inventory Management inside Transaction
    try:
        flight = db.query(models.Flight).with_for_update().filter(
            models.Flight.id == booking_in.flight_id
        ).first()
        
        if not flight:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Flight not found"
            )

        seat_cls = booking_in.seat_class.upper() if isinstance(booking_in.seat_class, str) else booking_in.seat_class.value

        if seat_cls == models.SeatClass.FIRST:
            updated_rows = db.query(models.Flight).filter(
                models.Flight.id == booking_in.flight_id,
                models.Flight.available_first >= booking_in.seats
            ).update(
                {models.Flight.available_first: models.Flight.available_first - booking_in.seats},
                synchronize_session=False
            )
        elif seat_cls == models.SeatClass.BUSINESS:
            updated_rows = db.query(models.Flight).filter(
                models.Flight.id == booking_in.flight_id,
                models.Flight.available_business >= booking_in.seats
            ).update(
                {models.Flight.available_business: models.Flight.available_business - booking_in.seats},
                synchronize_session=False
            )
        elif seat_cls == models.SeatClass.ECONOMY:
            updated_rows = db.query(models.Flight).filter(
                models.Flight.id == booking_in.flight_id,
                models.Flight.available_economy >= booking_in.seats
            ).update(
                {models.Flight.available_economy: models.Flight.available_economy - booking_in.seats},
                synchronize_session=False
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid seat class: '{booking_in.seat_class}'"
            )

        if updated_rows == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient inventory for {seat_cls} class"
            )

        # 6. Create Booking & Idempotency Record
        booking_ref = str(uuid.uuid4())[:8].upper()
        db_booking = models.Booking(
            flight_id=booking_in.flight_id,
            passenger_id=booking_in.passenger_id,
            fare_type=booking_in.fare_type.upper(),
            seat_class=seat_cls,
            seats=booking_in.seats,
            amount=booking_in.amount,
            booking_reference=booking_ref,
            status=models.BookingStatus.CONFIRMED
        )
        db.add(db_booking)
        db.flush()

        if key:
            resp_dict = {
                "id": db_booking.id,
                "booking_reference": db_booking.booking_reference,
                "flight_id": db_booking.flight_id,
                "passenger_id": db_booking.passenger_id,
                "fare_type": db_booking.fare_type,
                "seat_class": db_booking.seat_class,
                "seats": db_booking.seats,
                "amount": db_booking.amount,
                "status": db_booking.status,
                "created_at": db_booking.created_at.isoformat() if db_booking.created_at else None
            }
            idem_record = models.IdempotencyRecord(
                idempotency_key=key,
                booking_id=db_booking.id,
                response_json=json.dumps(resp_dict)
            )
            db.add(idem_record)

        db.commit()
        db.refresh(db_booking)
        return db_booking

    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        if key:
            existing = db.query(models.IdempotencyRecord).filter(
                models.IdempotencyRecord.idempotency_key == key
            ).first()
            if existing and existing.booking_id:
                booking = db.query(models.Booking).filter(
                    models.Booking.id == existing.booking_id
                ).first()
                if booking:
                    return booking
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database integrity error during booking execution."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction failed: {str(e)}"
        )

def cancel_booking(booking_id: int, db: Session) -> schemas.CancellationResponse:
    # 1. Fetch Booking
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # 2. Prevent Double Cancellation
    if booking.status.startswith("CANCELLED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking is already cancelled (status: {booking.status})"
        )

    # 3. Fare Policy Branching (Check schedule change override first)
    if getattr(booking, "schedule_change_override", False):
        new_status = "CANCELLED_REFUNDED"
        msg = "Booking cancelled. Full refund approved due to airline schedule change."
    else:
        fare_type_clean = booking.fare_type.upper()
        fare_rule = db.query(models.FareRule).filter(
            models.FareRule.fare_type == fare_type_clean
        ).first()

        if fare_rule:
            if fare_rule.refundable:
                new_status = "CANCELLED_REFUNDED"
                msg = "Booking cancelled. Full refund approved per fare policy."
            elif fare_rule.credit_allowed:
                new_status = "CANCELLED_CREDIT"
                msg = "Booking cancelled. Travel credit issued per fare policy."
            else:
                new_status = "CANCELLED_NO_REFUND"
                msg = "Booking cancelled. Non-refundable fare."
        else:
            if fare_type_clean == "FLEXIBLE":
                new_status = "CANCELLED_REFUNDED"
                msg = "Booking cancelled. Refund approved per Flexible policy."
            elif fare_type_clean == "STANDARD":
                new_status = "CANCELLED_CREDIT"
                msg = "Booking cancelled. Travel credit issued per Standard policy."
            else:
                new_status = "CANCELLED_NO_REFUND"
                msg = "Booking cancelled. Non-refundable fare."

    # 4. Atomic Inventory Restoration with Row Locking
    try:
        flight = db.query(models.Flight).with_for_update().filter(
            models.Flight.id == booking.flight_id
        ).first()

        if flight:
            seat_cls = booking.seat_class.upper()
            if seat_cls == models.SeatClass.FIRST:
                flight.available_first = min(flight.first_seats, flight.available_first + booking.seats)
            elif seat_cls == models.SeatClass.BUSINESS:
                flight.available_business = min(flight.business_seats, flight.available_business + booking.seats)
            elif seat_cls == models.SeatClass.ECONOMY:
                flight.available_economy = min(flight.economy_seats, flight.available_economy + booking.seats)

        # 5. Update Status
        booking.status = new_status

        # 6. Record AuditLog
        audit = models.AuditLog(
            entity_type="BOOKING",
            entity_id=booking.id,
            action="CANCEL_BOOKING",
            actor="PASSENGER",
            details=f"Booking {booking.booking_reference} cancelled. Status set to {new_status}. Restored {booking.seats} {booking.seat_class} seats."
        )
        db.add(audit)

        db.commit()
        db.refresh(booking)

        return schemas.CancellationResponse(
            booking_id=booking.id,
            booking_reference=booking.booking_reference,
            status=new_status,
            seats_restored=booking.seats,
            fare_type=booking.fare_type,
            message=msg
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cancellation failed: {str(e)}"
        )
