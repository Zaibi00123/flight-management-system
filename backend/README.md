# Flight Management System - Backend & Frontend

Hackathon deliverable for the Flight Management System (FastAPI + Neon PostgreSQL + Single-Page Frontend).

## 1. Setup & Starting FastAPI Backend
```bash
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```
- **Live API:** `http://127.0.0.1:8000`
- **Swagger Documentation:** `http://127.0.0.1:8000/docs`
- **Health Check:** `http://127.0.0.1:8000/health`

## 2. Starting Frontend
Open `http://127.0.0.1:8000/app` or `frontend/index.html`.

## 3. Running Automated Test Suite
```bash
cd backend
pytest
python tests/test_step8_live_e2e.py
```

## 4. Endpoints Summary (Steps 3 - 8)
- `GET /health`
- `GET /api/search/flights`
- `POST /api/bookings/`, `GET /api/bookings/{id}`
- `POST /api/bookings/{id}/cancel`
- `POST /api/waitlist/`, `GET /api/waitlist/{flight_id}`
- `POST /api/admin/flights`, `PATCH /api/admin/flights/{id}`
- `POST /api/admin/flights/{id}/cancel`
- `GET /api/admin/audit-logs`

## 5. End-to-End Checklist Results (All 12 PASS)
1. Search route/date matches inventory: PASS
2. Create booking decrements inventory: PASS
3. Retry same idempotency key avoids duplicate: PASS
4. Lookup booking by ID matches record: PASS
5. Cancel booking restores inventory & branches policy: PASS
6. Waitlist rejected if seats available: PASS
7. Waitlist joins & queues when class full: PASS
8. Admin created flight appears in search: PASS
9. Admin edit schedule >= 60m sets schedule_change_override: PASS
10. Admin cancel flight cascades bookings to CANCELLED_REFUNDED: PASS
11. Ops-agent role cannot cancel flights (403): PASS
12. Audit log recorded in Neon for all admin/cancellation actions: PASS
