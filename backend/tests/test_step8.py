# pyrefly: ignore [missing-import]
import pytest
from datetime import datetime, timedelta, timezone
import uuid
import models

def test_step8_frontend_serving(client):
    res = client.get("/app")
    assert res.status_code == 200
    assert "Flight Management System" in res.text

def test_step8_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "database" in data

def test_step8_admin_audit_logs_retrieval(client, db):
    # Ensure at least one audit log exists
    audit = models.AuditLog(
        entity_type="SYSTEM",
        entity_id=1,
        action="TEST_ACTION",
        actor="super-admin",
        details="Test details"
    )
    db.add(audit)
    db.commit()

    res = client.get("/api/admin/audit-logs", headers={"X-Admin-Role": "super-admin"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert any(log["action"] == "TEST_ACTION" for log in data)

def test_step8_e2e_full_lifecycle(client, db):
    now = datetime.now(timezone.utc)
    fl = models.Flight(
        flight_number="STEP8-101",
        origin="ISB",
        destination="LHE",
        departure_time=now + timedelta(days=2),
        arrival_time=now + timedelta(days=2, hours=1),
        total_seats=2,
        first_seats=0,
        business_seats=0,
        economy_seats=2,
        available_first=0,
        available_business=0,
        available_economy=2,
        status=models.FlightStatus.SCHEDULED
    )
    pax = models.Passenger(name="Lifecycle Pax", email="pax_s8@test.com")
    db.add_all([fl, pax])
    db.commit()

    # 1. Search
    s_res = client.get("/api/search/flights", params={"origin": "ISB", "destination": "LHE"})
    assert s_res.status_code == 200
    assert any(f["id"] == fl.id for f in s_res.json())

    # 2. Book
    idem_key = "s8-idem-" + uuid.uuid4().hex
    b_res = client.post("/api/bookings/", headers={"Idempotency-Key": idem_key}, json={
        "flight_id": fl.id,
        "passenger_id": pax.id,
        "seat_class": "ECONOMY",
        "seats": 1,
        "fare_type": "STANDARD",
        "amount": 100.0
    })
    assert b_res.status_code == 201
    booking_id = b_res.json()["id"]

    # 3. Retry booking (Idempotency)
    b_retry = client.post("/api/bookings/", headers={"Idempotency-Key": idem_key}, json={
        "flight_id": fl.id,
        "passenger_id": pax.id,
        "seat_class": "ECONOMY",
        "seats": 1,
        "fare_type": "STANDARD",
        "amount": 100.0
    })
    assert b_retry.json()["id"] == booking_id

    # 4. Lookup
    lookup = client.get(f"/api/bookings/{booking_id}")
    assert lookup.status_code == 200
    assert lookup.json()["status"] == "CONFIRMED"

    # 5. Cancel
    cancel = client.post(f"/api/bookings/{booking_id}/cancel")
    assert cancel.status_code == 200
    assert "CANCELLED" in cancel.json()["status"]
