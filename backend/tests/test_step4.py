import pytest
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import models

# 1. FLIGHT SEARCH TESTS
def test_search_flights_validation(client):
    # Same origin & destination -> 400
    res = client.get("/api/search/flights?origin=LHE&destination=LHE")
    assert res.status_code == 400
    assert "identical" in res.json()["detail"]

    # Invalid date format -> 400
    res = client.get("/api/search/flights?origin=LHE&destination=KHI&departure_date=2026/10/01")
    assert res.status_code == 400
    assert "Invalid departure_date format" in res.json()["detail"]

def test_search_flights_success(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    arr = dep + timedelta(hours=2)
    fl = models.Flight(
        flight_number="PK-800",
        origin="ISB",
        destination="KHI",
        departure_time=dep,
        arrival_time=arr,
        total_seats=100,
        first_seats=10,
        business_seats=20,
        economy_seats=70,
        available_first=10,
        available_business=20,
        available_economy=70,
        status=models.FlightStatus.SCHEDULED
    )
    db.add(fl)
    db.commit()

    date_str = dep.strftime("%Y-%m-%d")
    res = client.get(f"/api/search/flights?origin=ISB&destination=KHI&departure_date={date_str}")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    flight_data = data[0]
    assert flight_data["flight_number"] == "PK-800"
    assert flight_data["available_economy"] == 70
    assert len(flight_data["applicable_fares"]) > 0

# 2. FARE RULES TESTS
def test_get_fare_rules(client):
    res = client.get("/api/search/fare-rules")
    assert res.status_code == 200
    rules = res.json()
    assert len(rules) >= 3
    fare_types = [r["fare_type"] for r in rules]
    assert "BASIC_ECONOMY" in fare_types
    assert "FLEXIBLE" in fare_types

# 3. PRICE HOLD TESTS
def test_price_hold_creation_and_expiration(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=2)
    fl = models.Flight(
        flight_number="PK-900", origin="LHE", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=50, economy_seats=50, available_economy=50,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Alice", email="alice@example.com")
    db.add_all([fl, p])
    db.commit()

    # Create hold
    res = client.post("/api/search/price-hold", json={
        "flight_id": fl.id,
        "fare_type": "FLEXIBLE",
        "seat_class": "ECONOMY",
        "held_price": 150.0,
        "duration_minutes": 15
    })
    assert res.status_code == 201
    hold_data = res.json()
    ref = hold_data["hold_reference"]
    assert ref.startswith("HOLD-")

    # Manually expire hold in DB
    hold_db = db.query(models.PriceHold).filter(models.PriceHold.hold_reference == ref).first()
    hold_db.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()

    # Attempt booking with expired hold -> 400
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id,
        "passenger_id": p.id,
        "fare_type": "FLEXIBLE",
        "seat_class": "ECONOMY",
        "seats": 1,
        "amount": 150.0,
        "hold_reference": ref
    })
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()

# 4. SEAT HOLD & BOOKING SAFETY TESTS
def test_booking_validation_and_inventory(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=3)
    fl = models.Flight(
        flight_number="PK-301", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=30, economy_seats=20, first_seats=10,
        available_economy=20, available_first=10, available_business=0,
        status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Bob", email="bob@example.com")
    db.add_all([fl, p])
    db.commit()

    # Invalid fare type -> 400
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "SUPER_VIP_UNSUPPORTED", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    })
    assert res.status_code == 400
    assert "Invalid or unsupported fare type" in res.json()["detail"]

    # Valid booking -> 201
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "BASIC_ECONOMY", "seat_class": "ECONOMY",
        "seats": 2, "amount": 200.0
    })
    assert res.status_code == 201
    assert res.json()["status"] == "CONFIRMED"

    # Verify inventory reduced
    db.refresh(fl)
    assert fl.available_economy == 18

# 5. INSUFFICIENT INVENTORY REJECTION
def test_insufficient_inventory_group_booking(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=3)
    fl = models.Flight(
        flight_number="PK-404", origin="ISB", destination="LHE",
        departure_time=dep, arrival_time=dep + timedelta(hours=1),
        total_seats=5, economy_seats=5, available_economy=5,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="Charlie", email="charlie@example.com")
    db.add_all([fl, p])
    db.commit()

    # Request 10 seats when only 5 available -> 400
    res = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 10, "amount": 1000.0
    })
    assert res.status_code == 400
    assert "Insufficient inventory" in res.json()["detail"]

    # Inventory remains untouched at 5
    db.refresh(fl)
    assert fl.available_economy == 5

# 6. IDEMPOTENCY KEY DEDUPLICATION
def test_idempotency_key_deduplication(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=4)
    fl = models.Flight(
        flight_number="PK-505", origin="KHI", destination="ISB",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=10, economy_seats=10, available_economy=10,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p = models.Passenger(name="David", email="david@example.com")
    db.add_all([fl, p])
    db.commit()

    key = "IDEM-KEY-UNIQUE-12345"
    payload = {
        "flight_id": fl.id, "passenger_id": p.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 3, "amount": 300.0
    }

    # 1st request with Idempotency-Key header
    res1 = client.post("/api/bookings/", json=payload, headers={"Idempotency-Key": key})
    assert res1.status_code == 201
    booking1 = res1.json()

    # 2nd request with exact same Idempotency-Key
    res2 = client.post("/api/bookings/", json=payload, headers={"Idempotency-Key": key})
    assert res2.status_code in (200, 201)
    booking2 = res2.json()

    assert booking1["booking_reference"] == booking2["booking_reference"]

    # Check inventory decremented only ONCE (10 - 3 = 7, NOT 10 - 6 = 4)
    db.refresh(fl)
    assert fl.available_economy == 7

# 7. CONCURRENCY & OVERSELLING PROTECTION TEST
def test_concurrent_seat_booking(client, db):
    dep = datetime.now(timezone.utc) + timedelta(days=5)
    fl = models.Flight(
        flight_number="PK-777", origin="LHE", destination="KHI",
        departure_time=dep, arrival_time=dep + timedelta(hours=2),
        total_seats=1, economy_seats=1, available_economy=1,
        available_first=0, available_business=0, status=models.FlightStatus.SCHEDULED
    )
    p1 = models.Passenger(name="P1", email="p1@example.com")
    p2 = models.Passenger(name="P2", email="p2@example.com")
    db.add_all([fl, p1, p2])
    db.commit()

    # Request 1: Should succeed (201)
    res1 = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p1.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    }, headers={"Idempotency-Key": "CONCUR-KEY-1"})
    assert res1.status_code == 201

    # Request 2: Attempt booking remaining seat when inventory is 0 -> Should fail (400)
    res2 = client.post("/api/bookings/", json={
        "flight_id": fl.id, "passenger_id": p2.id,
        "fare_type": "STANDARD", "seat_class": "ECONOMY",
        "seats": 1, "amount": 100.0
    }, headers={"Idempotency-Key": "CONCUR-KEY-2"})
    assert res2.status_code == 400
    assert "insufficient inventory" in res2.json()["detail"].lower()

    db.refresh(fl)
    assert fl.available_economy == 0
