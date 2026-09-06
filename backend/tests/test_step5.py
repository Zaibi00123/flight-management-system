# pyrefly: ignore [missing-import]
import pytest
from datetime import datetime, timedelta, timezone
import models

# 1. CANCELLATION POLICY BRANCHING & INVENTORY RESTORATION TESTS
def test_cancellation_refundable_policy(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=3)
    fl = models.Flight(
        flight_number="PK-101", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=20, economy_seats=20, available_economy=18,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Alice", email="alice_cancel@example.com")
    db.add_all([fl, p])
    db.commit()

    # Create refundable booking
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "FLEXIBLE", "seat_class": "ECONOMY",
        "seats": 2, "amount": 200.0
    })
    assert res.status_code == 201
    booking_id = res.json()["id"]

    db.refresh(fl)
    assert fl.available_economy == 16

    # Cancel booking
    res_cancel = client.post(f"/api/bookings/{booking_id}/cancel")
    assert res_cancel.status_code == 200
    cancel_data = res_cancel.json()
    assert cancel_data["status"] == "CANCELLED_REFUNDED"
    assert cancel_data["seats_restored"] == 2

    # Verify inventory restored
    db.refresh(fl)
    assert fl.available_economy == 18

    # Verify AuditLog created
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "BOOKING",
        models.AuditLog.entity_id == booking_id
    ).first()
    assert audit is not None
    assert audit.action == "CANCEL_BOOKING"
    assert "CANCELLED_REFUNDED" in audit.details

def test_cancellation_non_refundable_policy(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=3)
    fl = models.Flight(
        flight_number="PK-102", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=10, economy_seats=10, available_economy=10,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Bob", email="bob_cancel@example.com")
    db.add_all([fl, p])
    db.commit()

    # Create basic economy booking
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "BASIC_ECONOMY", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })
    assert res.status_code == 201
    booking_id = res.json()["id"]

    # Cancel basic economy booking -> CANCELLED_NO_REFUND
    res_cancel = client.post(f"/api/bookings/{booking_id}/cancel")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "CANCELLED_NO_REFUND"

    # Inventory still restored
    db.refresh(fl)
    assert fl.available_economy == 10

def test_prevent_double_cancellation(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=3)
    fl = models.Flight(
        flight_number="PK-103", origin="ISB", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=5, economy_seats=5, available_economy=5,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Charlie", email="charlie_cancel@example.com")
    db.add_all([fl, p])
    db.commit()

    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })
    booking_id = res.json()["id"]

    # 1st Cancellation -> 200
    res1 = client.post(f"/api/bookings/{booking_id}/cancel")
    assert res1.status_code == 200

    # 2nd Cancellation -> 400
    res2 = client.post(f"/api/bookings/{booking_id}/cancel")
    assert res2.status_code == 400
    assert "already cancelled" in res2.json()["detail"].lower()

def test_cancel_non_existent_booking(client):
    res = client.post("/api/bookings/999999/cancel")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

# 2. WAITLIST JOIN TESTS
def test_waitlist_join_rejection_when_seats_available(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=4)
    fl = models.Flight(
        flight_number="PK-201", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=10, economy_seats=10, available_economy=5,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="David", email="david_waitlist@example.com")
    db.add_all([fl, p])
    db.commit()

    # Attempt joining waitlist when 5 seats available -> 400
    res = client.post("/api/waitlist/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "seat_class": "ECONOMY", "priority": 1
    })
    assert res.status_code == 400
    assert "available" in res.json()["detail"].lower()

def test_waitlist_join_success_when_full(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=4)
    fl = models.Flight(
        flight_number="PK-202", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=5, economy_seats=5, available_economy=0,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Eve", email="eve_waitlist@example.com")
    db.add_all([fl, p])
    db.commit()

    # Join waitlist when full -> 201
    res = client.post("/api/waitlist/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "seat_class": "ECONOMY", "priority": 1
    })
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "PENDING"
    assert data["flight_id"] == fl.id

    # Verify GET waitlist
    res_get = client.get(f"/api/waitlist/{fl.id}")
    assert res_get.status_code == 200
    entries = res_get.json()
    assert len(entries) == 1
    assert entries[0]["passenger_id"] == p.id

    # Verify AuditLog created
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "WAITLIST",
        models.AuditLog.entity_id == data["id"]
    ).first()
    assert audit is not None
    assert audit.action == "JOIN_WAITLIST"
