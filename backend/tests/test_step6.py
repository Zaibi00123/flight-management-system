# pyrefly: ignore [missing-import]
import pytest
from datetime import datetime, timedelta, timezone
import models

# 1. ROLE GATING TESTS
def test_admin_role_header_required(client):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    arr = dep + timedelta(hours=2)
    payload = {
        "flight_number": "PK-801", "origin": "LHE", "destination": "KHI",
        "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
        "total_seats": 100, "first_seats": 10, "business_seats": 20, "economy_seats": 70
    }

    # Missing header -> 403
    res_no_header = client.post("/api/admin/flights", json=payload)
    assert res_no_header.status_code == 403

    # Invalid header -> 403
    res_bad_header = client.post("/api/admin/flights", json=payload, headers={"X-Admin-Role": "guest"})
    assert res_bad_header.status_code == 403

# 2. CREATE FLIGHT VALIDATION TESTS
def test_create_flight_validations(client):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    arr = dep + timedelta(hours=2)
    headers = {"X-Admin-Role": "super-admin"}

    # Seat sum mismatch -> 400
    res = client.post("/api/admin/flights", headers=headers, json={
        "flight_number": "PK-802", "origin": "LHE", "destination": "ISB",
        "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
        "total_seats": 100, "first_seats": 10, "business_seats": 20, "economy_seats": 50 # Sum 80 != 100
    })
    assert res.status_code == 400
    assert "must equal" in res.json()["detail"].lower()

    # Identical origin & destination -> 400
    res = client.post("/api/admin/flights", headers=headers, json={
        "flight_number": "PK-803", "origin": "LHE", "destination": "LHE",
        "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
        "total_seats": 50, "first_seats": 0, "business_seats": 0, "economy_seats": 50
    })
    assert res.status_code == 400
    assert "identical" in res.json()["detail"].lower()

    # Departure after arrival -> 400
    res = client.post("/api/admin/flights", headers=headers, json={
        "flight_number": "PK-804", "origin": "LHE", "destination": "KHI",
        "departure_time": arr.isoformat(), "arrival_time": dep.isoformat(),
        "total_seats": 50, "first_seats": 0, "business_seats": 0, "economy_seats": 50
    })
    assert res.status_code == 400
    assert "after" in res.json()["detail"].lower()

# 3. SUCCESSFUL FLIGHT CREATION & AUDIT LOG TEST
def test_create_flight_success(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=6)
    arr = dep + timedelta(hours=2)
    headers = {"X-Admin-Role": "super-admin"}

    res = client.post("/api/admin/flights", headers=headers, json={
        "flight_number": "PK-990", "origin": "ISB", "destination": "KHI",
        "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
        "total_seats": 60, "first_seats": 10, "business_seats": 10, "economy_seats": 40
    })
    assert res.status_code == 201
    data = res.json()
    assert data["flight_number"] == "PK-990"
    assert data["available_first"] == 10
    assert data["available_business"] == 10
    assert data["available_economy"] == 40
    assert data["active_bookings_affected"] is False

    # Check AuditLog entry
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "FLIGHT",
        models.AuditLog.entity_id == data["id"]
    ).first()
    assert audit is not None
    assert audit.action == "CREATE_FLIGHT"
    assert audit.actor == "super-admin"

# 4. DUPLICATE FLIGHT DETECTION TEST
def test_duplicate_flight_rejection(client):
    dep = datetime.now(timezone.utc) + timedelta(days=7)
    arr = dep + timedelta(hours=2)
    headers = {"X-Admin-Role": "ops-agent"}

    payload = {
        "flight_number": "PK-DUP1", "origin": "LHE", "destination": "ISB",
        "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
        "total_seats": 50, "first_seats": 0, "business_seats": 10, "economy_seats": 40
    }

    # 1st creation -> 201
    res1 = client.post("/api/admin/flights", headers=headers, json=payload)
    assert res1.status_code == 201

    # 2nd creation (duplicate same day & route) -> 409
    res2 = client.post("/api/admin/flights", headers=headers, json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()

# 5. FLIGHT EDITING & SHRINK PROTECTION TESTS
def test_edit_flight_and_shrink_protection(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=8)
    fl = models.Flight(
        flight_number="PK-333", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=20, economy_seats=20, available_economy=20,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Grace", email="grace@example.com")
    db.add_all([fl, p])
    db.commit()

    # Book 5 economy seats -> 15 available remaining (5 booked)
    client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 5, "amount": 500.0
    })

    # Attempt shrinking economy_seats to 3 (below 5 booked) -> 400
    res_shrink = client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "super-admin"}, json={
        "economy_seats": 3
    })
    assert res_shrink.status_code == 400
    assert "Cannot reduce" in res_shrink.json()["detail"]

    # Valid edit (increase economy_seats to 30) -> 200, active_bookings_affected: True
    res_edit = client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "super-admin"}, json={
        "economy_seats": 30
    })
    assert res_edit.status_code == 200
    data = res_edit.json()
    assert data["economy_seats"] == 30
    assert data["available_economy"] == 25 # 30 - 5 booked = 25
    assert data["active_bookings_affected"] is True

    # AuditLog entry created
    audit = db.query(models.AuditLog).filter(
        models.AuditLog.entity_type == "FLIGHT",
        models.AuditLog.entity_id == fl.id,
        models.AuditLog.action == "EDIT_FLIGHT"
    ).first()
    assert audit is not None

# 6. OPS-AGENT ROLE EDIT RESTRICTION TEST
def test_ops_agent_edit_restriction(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=9)
    fl = models.Flight(
        flight_number="PK-444", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=10, economy_seats=10, available_economy=10,
        first_seats=0, business_seats=0, available_first=0, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Hank", email="hank@example.com")
    db.add_all([fl, p])
    db.commit()

    # Book 1 seat on flight
    client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })

    # ops-agent tries to edit flight with active bookings -> 403 Forbidden
    res_ops = client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "ops-agent"}, json={
        "economy_seats": 15
    })
    assert res_ops.status_code == 403
    assert "not authorized" in res_ops.json()["detail"].lower()

    # super-admin tries to edit same flight -> 200 OK
    res_super = client.patch(f"/api/admin/flights/{fl.id}", headers={"X-Admin-Role": "super-admin"}, json={
        "economy_seats": 15
    })
    assert res_super.status_code == 200
