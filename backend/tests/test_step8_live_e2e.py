# pyrefly: ignore [missing-import]
import httpx
import uuid
from datetime import datetime, timedelta, timezone

API_BASE = "http://127.0.0.1:8000"

def run_12_checks():
    results = {}
    print("=== STARTING STEP 8 END-TO-END LIVE 12-CHECKS PASS ===")

    client = httpx.Client(base_url=API_BASE, timeout=10.0)

    # Setup: Create unique flight and passenger for clear tracking
    unique_suffix = uuid.uuid4().hex[:6].upper()
    flight_num = f"E2E-{unique_suffix}"
    now = datetime.now(timezone.utc)
    dep_time = (now + timedelta(days=2)).isoformat()
    arr_time = (now + timedelta(days=2, hours=3)).isoformat()

    # Step 0: Ensure we have a passenger
    pax_res = client.post("/api/passengers/", json={
        "name": f"Tester {unique_suffix}",
        "email": f"tester_{unique_suffix}@demo.com",
        "phone": "+1-555-0199"
    })
    assert pax_res.status_code == 201, f"Passenger creation failed: {pax_res.text}"
    pax_id = pax_res.json()["id"]

    # Also seed a flight via admin for checks 1-7
    admin_headers = {"X-Admin-Role": "super-admin"}
    fl_res = client.post("/api/admin/flights", headers=admin_headers, json={
        "flight_number": flight_num,
        "origin": "DXB",
        "destination": "LHR",
        "departure_time": dep_time,
        "arrival_time": arr_time,
        "total_seats": 5,
        "first_seats": 0,
        "business_seats": 2,
        "economy_seats": 3
    })
    assert fl_res.status_code == 201, f"Setup flight creation failed: {fl_res.text}"
    fl_data = fl_res.json()
    flight_id = fl_data["id"]

    # ----------------------------------------------------
    # CHECK 1: Search route/date -> confirm results match inventory
    # ----------------------------------------------------
    try:
        s_res = client.get("/api/search/flights", params={
            "origin": "DXB",
            "destination": "LHR",
            "departure_date": dep_time[:10]
        })
        assert s_res.status_code == 200, f"Search failed: {s_res.text}"
        found = [f for f in s_res.json() if f["id"] == flight_id]
        assert len(found) == 1, "Flight not found in search results"
        assert found[0]["available_economy"] == 3, f"Expected 3 economy, got {found[0]['available_economy']}"
        results[1] = "PASS"
        print("Check 1 (Search Route/Date): PASS")
    except Exception as e:
        results[1] = f"FAIL: {e}"
        print(f"Check 1: {results[1]}")

    # ----------------------------------------------------
    # CHECK 2: Create booking -> confirm booking succeeds and inventory decreases
    # ----------------------------------------------------
    idem_key = str(uuid.uuid4())
    try:
        b_res = client.post("/api/bookings/", headers={"Idempotency-Key": idem_key}, json={
            "flight_id": flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "seats": 1,
            "fare_type": "STANDARD",
            "amount": 250.00
        })
        assert b_res.status_code == 201, f"Booking creation failed: {b_res.text}"
        booking_data = b_res.json()
        booking_id = booking_data["id"]

        # Check inventory
        check_fl = client.get(f"/api/flights/{flight_id}").json()
        assert check_fl["available_economy"] == 2, f"Expected 2 available_economy, got {check_fl['available_economy']}"
        results[2] = "PASS"
        print("Check 2 (Create Booking & Inventory Decrement): PASS")
    except Exception as e:
        results[2] = f"FAIL: {e}"
        print(f"Check 2: {results[2]}")

    # ----------------------------------------------------
    # CHECK 3: Retry same booking submission (same idempotency key) -> confirm no duplicate booking & no double inventory decrement
    # ----------------------------------------------------
    try:
        retry_res = client.post("/api/bookings/", headers={"Idempotency-Key": idem_key}, json={
            "flight_id": flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "seats": 1,
            "fare_type": "STANDARD",
            "amount": 250.00
        })
        retry_data = retry_res.json()
        assert retry_data["id"] == booking_id, f"Expected booking ID {booking_id}, got {retry_data['id']}"

        # Verify inventory was NOT decremented again
        check_fl2 = client.get(f"/api/flights/{flight_id}").json()
        assert check_fl2["available_economy"] == 2, f"Inventory was double decremented! Current: {check_fl2['available_economy']}"
        results[3] = "PASS"
        print("Check 3 (Idempotency Retry Protection): PASS")
    except Exception as e:
        results[3] = f"FAIL: {e}"
        print(f"Check 3: {results[3]}")

    # ----------------------------------------------------
    # CHECK 4: Look up booking by ID -> confirm details match
    # ----------------------------------------------------
    try:
        lookup_res = client.get(f"/api/bookings/{booking_id}")
        assert lookup_res.status_code == 200, f"Lookup failed: {lookup_res.text}"
        looked_data = lookup_res.json()
        assert looked_data["booking_reference"] == booking_data["booking_reference"]
        assert looked_data["flight_id"] == flight_id
        assert looked_data["passenger_id"] == pax_id
        assert looked_data["seat_class"] == "ECONOMY"
        assert looked_data["status"] == "CONFIRMED"
        results[4] = "PASS"
        print("Check 4 (Lookup Booking by ID): PASS")
    except Exception as e:
        results[4] = f"FAIL: {e}"
        print(f"Check 4: {results[4]}")

    # ----------------------------------------------------
    # CHECK 5: Cancel booking -> confirm status updates and inventory is restored
    # ----------------------------------------------------
    try:
        cancel_res = client.post(f"/api/bookings/{booking_id}/cancel")
        assert cancel_res.status_code == 200, f"Cancel failed: {cancel_res.text}"
        c_data = cancel_res.json()
        assert c_data["seats_restored"] == 1
        assert "CANCELLED" in c_data["status"]

        # Verify inventory restored
        check_fl3 = client.get(f"/api/flights/{flight_id}").json()
        assert check_fl3["available_economy"] == 3, f"Inventory not restored! Current: {check_fl3['available_economy']}"
        results[5] = "PASS"
        print("Check 5 (Cancel Booking & Inventory Restored): PASS")
    except Exception as e:
        results[5] = f"FAIL: {e}"
        print(f"Check 5: {results[5]}")

    # ----------------------------------------------------
    # CHECK 6: Attempt to join waitlist on a flight/class that is NOT full -> confirm rejected
    # ----------------------------------------------------
    try:
        # Currently flight has available_economy = 3 (NOT full)
        wl_reject_res = client.post("/api/waitlist/", json={
            "flight_id": flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "priority": 1
        })
        assert wl_reject_res.status_code == 400, f"Expected 400 rejected, got {wl_reject_res.status_code}"
        assert "available" in wl_reject_res.text.lower()
        results[6] = "PASS"
        print("Check 6 (Waitlist Rejected when seats available): PASS")
    except Exception as e:
        results[6] = f"FAIL: {e}"
        print(f"Check 6: {results[6]}")

    # ----------------------------------------------------
    # CHECK 7: Fill a class to zero via bookings, then join waitlist -> confirm succeeds and appears in queue
    # ----------------------------------------------------
    try:
        # Book remaining 3 economy seats
        b_fill = client.post("/api/bookings/", json={
            "flight_id": flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "seats": 3,
            "fare_type": "STANDARD",
            "amount": 750.00
        })
        assert b_fill.status_code == 201, f"Failed to fill seats: {b_fill.text}"

        check_full = client.get(f"/api/flights/{flight_id}").json()
        assert check_full["available_economy"] == 0, f"Expected 0 seats, got {check_full['available_economy']}"

        # Now join waitlist
        wl_join = client.post("/api/waitlist/", json={
            "flight_id": flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "priority": 1
        })
        assert wl_join.status_code == 201, f"Waitlist join failed: {wl_join.text}"
        wl_data = wl_join.json()

        # Check waitlist list
        wl_list = client.get(f"/api/waitlist/{flight_id}").json()
        matching_wl = [w for w in wl_list if w["id"] == wl_data["id"]]
        assert len(matching_wl) == 1, "Waitlist entry not in queue list"
        results[7] = "PASS"
        print("Check 7 (Waitlist Joins & Appears in Queue when class full): PASS")
    except Exception as e:
        results[7] = f"FAIL: {e}"
        print(f"Check 7: {results[7]}")

    # ----------------------------------------------------
    # CHECK 8: As admin (super-admin role header): create a new flight -> confirm it appears in search results
    # ----------------------------------------------------
    admin_flight_num = f"ADM-{uuid.uuid4().hex[:6].upper()}"
    new_dep = (now + timedelta(days=3)).isoformat()
    new_arr = (now + timedelta(days=3, hours=2)).isoformat()
    try:
        create_fl_res = client.post("/api/admin/flights", headers={"X-Admin-Role": "super-admin"}, json={
            "flight_number": admin_flight_num,
            "origin": "ISB",
            "destination": "KHI",
            "departure_time": new_dep,
            "arrival_time": new_arr,
            "total_seats": 50,
            "first_seats": 5,
            "business_seats": 10,
            "economy_seats": 35
        })
        assert create_fl_res.status_code == 201, f"Admin flight create failed: {create_fl_res.text}"
        new_flight_id = create_fl_res.json()["id"]

        # Search for this new flight
        search_new = client.get("/api/search/flights", params={
            "origin": "ISB",
            "destination": "KHI",
            "departure_date": new_dep[:10]
        }).json()
        assert any(f["id"] == new_flight_id for f in search_new), "Admin-created flight not in search results"
        results[8] = "PASS"
        print("Check 8 (Admin Create Flight & Appear in Search): PASS")
    except Exception as e:
        results[8] = f"FAIL: {e}"
        print(f"Check 8: {results[8]}")

    # ----------------------------------------------------
    # CHECK 9: As admin: edit that flight's schedule beyond threshold -> confirm active bookings get schedule_change_override = true
    # ----------------------------------------------------
    try:
        # Create an active booking on this new flight first
        book_fl2 = client.post("/api/bookings/", json={
            "flight_id": new_flight_id,
            "passenger_id": pax_id,
            "seat_class": "ECONOMY",
            "seats": 1,
            "fare_type": "STANDARD",
            "amount": 100.00
        })
        assert book_fl2.status_code == 201, f"Booking on new flight failed: {book_fl2.text}"
        b2_id = book_fl2.json()["id"]

        # Edit schedule by +3 hours (>= 60 minutes threshold)
        shifted_dep = (now + timedelta(days=3, hours=3)).isoformat()
        shifted_arr = (now + timedelta(days=3, hours=5)).isoformat()

        edit_res = client.patch(f"/api/admin/flights/{new_flight_id}", headers={"X-Admin-Role": "super-admin"}, json={
            "departure_time": shifted_dep,
            "arrival_time": shifted_arr
        })
        assert edit_res.status_code == 200, f"Edit flight failed: {edit_res.text}"
        assert edit_res.json()["active_bookings_affected"] is True

        # Check booking schedule_change_override
        b2_check = client.get(f"/api/bookings/{b2_id}").json()
        assert b2_check["schedule_change_override"] is True, f"schedule_change_override not set: {b2_check}"
        results[9] = "PASS"
        print("Check 9 (Admin Edit Schedule & Override Active Bookings): PASS")
    except Exception as e:
        results[9] = f"FAIL: {e}"
        print(f"Check 9: {results[9]}")

    # ----------------------------------------------------
    # CHECK 10: As admin: cancel that flight entirely -> confirm all active bookings cascade to cancelled_refunded
    # ----------------------------------------------------
    try:
        cancel_fl_res = client.post(f"/api/admin/flights/{new_flight_id}/cancel", headers={"X-Admin-Role": "super-admin"})
        assert cancel_fl_res.status_code == 200, f"Admin cancel flight failed: {cancel_fl_res.text}"
        c_fl_data = cancel_fl_res.json()
        assert c_fl_data["status"] == "CANCELLED"
        assert c_fl_data["cascaded_bookings_count"] >= 1

        # Check booking status
        b2_cancelled = client.get(f"/api/bookings/{b2_id}").json()
        assert b2_cancelled["status"] == "CANCELLED_REFUNDED", f"Expected CANCELLED_REFUNDED, got {b2_cancelled['status']}"
        results[10] = "PASS"
        print("Check 10 (Admin Cancel Flight Cascade to Active Bookings): PASS")
    except Exception as e:
        results[10] = f"FAIL: {e}"
        print(f"Check 10: {results[10]}")

    # ----------------------------------------------------
    # CHECK 11: As ops-agent role: attempt to cancel a flight -> confirm rejected (403)
    # ----------------------------------------------------
    try:
        # Create a temp flight to attempt cancellation
        fl_temp = client.post("/api/admin/flights", headers={"X-Admin-Role": "super-admin"}, json={
            "flight_number": f"TMP-{uuid.uuid4().hex[:6].upper()}",
            "origin": "LHE",
            "destination": "ISB",
            "departure_time": (now + timedelta(days=5)).isoformat(),
            "arrival_time": (now + timedelta(days=5, hours=1)).isoformat(),
            "total_seats": 30,
            "first_seats": 0,
            "business_seats": 5,
            "economy_seats": 25
        }).json()
        temp_id = fl_temp["id"]

        ops_cancel_res = client.post(f"/api/admin/flights/{temp_id}/cancel", headers={"X-Admin-Role": "ops-agent"})
        assert ops_cancel_res.status_code == 403, f"Expected 403 Forbidden, got {ops_cancel_res.status_code}"
        results[11] = "PASS"
        print("Check 11 (ops-agent Cancel Flight Rejected 403): PASS")
    except Exception as e:
        results[11] = f"FAIL: {e}"
        print(f"Check 11: {results[11]}")

    # ----------------------------------------------------
    # CHECK 12: Confirm audit log entries exist in Neon for every admin action and every cancellation performed above
    # ----------------------------------------------------
    try:
        audit_res = client.get("/api/admin/audit-logs", headers={"X-Admin-Role": "super-admin"})
        assert audit_res.status_code == 200, f"Audit logs retrieval failed: {audit_res.text}"
        logs = audit_res.json()
        actions = [l["action"] for l in logs]
        assert "CREATE_FLIGHT" in actions, "CREATE_FLIGHT missing from audit logs"
        assert "CANCEL_BOOKING" in actions, "CANCEL_BOOKING missing from audit logs"
        assert "JOIN_WAITLIST" in actions, "JOIN_WAITLIST missing from audit logs"
        assert "EDIT_FLIGHT" in actions, "EDIT_FLIGHT missing from audit logs"
        assert "CANCEL_FLIGHT_CASCADE" in actions, "CANCEL_FLIGHT_CASCADE missing from audit logs"
        results[12] = "PASS"
        print("Check 12 (Audit Log Entries in Neon): PASS")
    except Exception as e:
        results[12] = f"FAIL: {e}"
        print(f"Check 12: {results[12]}")

    print("\n=== SUMMARY OF 12 CHECKS ===")
    for k, v in results.items():
        print(f"Check {k}: {v}")

    client.close()
    return all(v == "PASS" for v in results.values())

if __name__ == "__main__":
    success = run_12_checks()
    exit(0 if success else 1)
