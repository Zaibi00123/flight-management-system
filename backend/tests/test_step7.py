# pyrefly: ignore [missing-import]
import pytest
from datetime import datetime, timedelta, timezone
import models

# 1. FLIGHT CANCELLATION CASCADE TESTS
def test_flight_cancellation_cascade_success(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    arr = dep + timedelta(hours=2)
    fl = models.Flight(
        flight_number="PK-701", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=arr,
        total_seats=50, economy_seats=50, available_economy=48,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    p1 = models.Passenger(name="User1", email="user1_cascade@example.com")
    p2 = models.Passenger(name="User2", email="user2_cascade@example.com")
    db.add_all([fl, p1, p2])
    db.commit()

    # Create 2 active bookings
    b1_res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p1.id,
        "fare_type": "BASIC_ECONOMY", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })
    b2_res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p2.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 1, "amount": 150.0
    })
    b1_id = b1_res.json()["id"]
    b2_id = b2_res.json()["id"]

    # Cancel flight as super-admin
    res_cancel = client.post(
        f"/api/admin/flights/{fl.id}/cancel",
        headers={"X-Admin-Role": "super-admin"}
    )
    assert res_cancel.status_code == 200
    data = res_cancel.json()
    assert data["status"] == "CANCELLED"
    assert data["cascaded_bookings_count"] == 2

    # Verify flight status updated
    db.refresh(fl)
    assert fl.status == "CANCELLED"

    # Verify bookings cascaded to CANCELLED_REFUNDED regardless of fare type
    b1 = db.query(models.Booking).filter(models.Booking.id == b1_id).first()
    b2 = db.query(models.Booking).filter(models.Booking.id == b2_id).first()
    assert b1.status == "CANCELLED_REFUNDED"
    assert b2.status == "CANCELLED_REFUNDED"

    # Verify single summary AuditLog entry created
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "FLIGHT",
        models.AuditLog.entity_id == fl.id,
        models.AuditLog.action == "CANCEL_FLIGHT_CASCADE"
    ).first()
    assert audit is not None
    assert audit.actor == "super-admin"
    assert "Cascaded 2 active bookings" in audit.details

def test_flight_cancellation_role_restriction(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    fl = models.Flight(
        flight_number="PK-702", origin="ISB", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=20, economy_seats=20, available_economy=20,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    db.add(fl)
    db.commit()

    # ops-agent tries cancelling flight -> 403 Forbidden
    res = client.post(
        f"/api/admin/flights/{fl.id}/cancel",
        headers={"X-Admin-Role": "ops-agent"}
    )
    assert res.status_code == 403
    assert "restricted" in res.json()["detail"].lower()

def test_duplicate_flight_cancellation_rejection(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    fl = models.Flight(
        flight_number="PK-703", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=10, economy_seats=10, available_economy=10,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    db.add(fl)
    db.commit()

    # 1st cancel -> 200
    res1 = client.post(f"/api/admin/flights/{fl.id}/cancel", headers={"X-Admin-Role": "super-admin"})
    assert res1.status_code == 200

    # 2nd cancel -> 400 Bad Request
    res2 = client.post(f"/api/admin/flights/{fl.id}/cancel", headers={"X-Admin-Role": "super-admin"})
    assert res2.status_code == 400
    assert "already cancelled" in res2.json()["detail"].lower()

# 2. SCHEDULE-CHANGE FARE-POLICY OVERRIDE TESTS
def test_schedule_change_override_threshold(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=10)
    arr = dep + timedelta(hours=2)
    fl = models.Flight(
        flight_number="PK-704", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=arr,
        total_seats=20, economy_seats=20, available_economy=19,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Ivy", email="ivy_schedule@example.com")
    db.add_all([fl, p])
    db.commit()

    # Create BASIC_ECONOMY booking (normally non-refundable)
    res_b = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "BASIC_ECONOMY", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })
    booking_id = res_b.json()["id"]

    # 1. Edit flight departure time by 30 mins (<= 60m threshold) -> override should remain False
    new_dep_30 = dep + timedelta(minutes=30)
    new_arr_30 = arr + timedelta(minutes=30)
    client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "super-admin"}, json={
        "departure_time": new_dep_30.isoformat(),
        "arrival_time": new_arr_30.isoformat()
    })

    b = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    assert b.schedule_change_override is False

    # 2. Edit flight departure time by 90 mins (> 60m threshold) -> override should become True
    new_dep_90 = dep + timedelta(minutes=90)
    new_arr_90 = arr + timedelta(minutes=90)
    res_patch = client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "super-admin"}, json={
        "departure_time": new_dep_90.isoformat(),
        "arrival_time": new_arr_90.isoformat()
    })
    assert res_patch.status_code == 200

    db.refresh(b)
    assert b.schedule_change_override is True

    # 3. Customer cancels BASIC_ECONOMY booking -> Should get CANCELLED_REFUNDED due to schedule_change_override!
    res_cancel = client.post(f"/api/bookings/{booking_id}/cancel")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "CANCELLED_REFUNDED"
    assert "schedule change" in res_cancel.json()["message"].lower()

    # Verify AuditLog created for threshold override
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "FLIGHT",
        models.AuditLog.entity_id == fl.id,
        models.AuditLog.action == "EDIT_FLIGHT"
    ).all()
    assert len(audit) >= 2
    last_audit = audit[-1]
    assert "exceeded 60m threshold" in last_audit.details
