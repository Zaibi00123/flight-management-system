# Flight Management System (FastAPI + Neon PostgreSQL + Frontend)

Hackathon deliverable for the Flight Management System, featuring a high-performance FastAPI transactional backend, Neon serverless PostgreSQL database integration, and a responsive single-page frontend.

---

## 1. How to Start the FastAPI Backend

### Environment Variables
Create a `.env` file inside `backend/.env` with your Neon PostgreSQL connection string:
```env
DATABASE_URL=postgresql://<user>:<password>@<neon-hostname>/<dbname>?sslmode=require
```
*(Note: If `DATABASE_URL` is omitted or contains placeholder credentials, the system safely uses local SQLite `sql_app.db` fallback for testing).*

### Running the Server
```bash
cd backend

# Windows PowerShell:
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000

# Linux / macOS:
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

* **Live API Base:** `http://127.0.0.1:8000`
* **Swagger UI Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **ReDoc Documentation:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
* **Health Check:** `http://127.0.0.1:8000/health`

---

## 2. How to Start the Frontend

The frontend is a zero-dependency, single-page application located in `frontend/index.html`.

### Option A: Via FastAPI (Recommended)
Once the FastAPI server is running, simply open:
👉 **[http://127.0.0.1:8000/app](http://127.0.0.1:8000/app)** or **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

### Option B: Direct File or Static Web Server
You can open `frontend/index.html` directly in any web browser, or run:
```bash
cd frontend
python -m http.server 3000
```
Then navigate to `http://localhost:3000`. The API Base URL input in the top header is pre-configured to `http://127.0.0.1:8000` (and CORS is enabled on the backend for all origins).

---

## 3. Full List of Endpoints (Steps 3 – 8)

| Method | Endpoint | Description | Auth / Headers |
|---|---|---|---|
| `GET` | `/health` | Live health & Neon database connection status | None |
| `GET` | `/api/search/flights` | Search flight inventory & applicable fares | None |
| `GET` | `/api/search/fare-rules` | Retrieve active fare rules & refund policies | None |
| `POST` | `/api/search/price-hold` | Hold a fare price for a specified window | None |
| `POST` | `/api/bookings/` | Create a booking with atomic inventory deduction | `Idempotency-Key` (Optional) |
| `GET` | `/api/bookings/{id}` | Lookup booking by ID & check status | None |
| `POST` | `/api/bookings/{id}/cancel` | Cancel booking, branch refund policy, restore seats | None |
| `POST` | `/api/waitlist/` | Join waitlist (enforces class inventory is 0) | None |
| `GET` | `/api/waitlist/{flight_id}` | View waitlist queue ordered by priority | None |
| `POST` | `/api/admin/flights` | Create flight with seat sum & route validations | `X-Admin-Role: super-admin` / `ops-agent` |
| `PATCH` | `/api/admin/flights/{id}` | Update flight schedule (>=60m trigger override) | `X-Admin-Role: super-admin` / `ops-agent` |
| `POST` | `/api/admin/flights/{id}/cancel` | Cancel entire flight & cascade refunds | `X-Admin-Role: super-admin` |
| `GET` | `/api/admin/audit-logs` | Retrieve recent audit trail from Neon | `X-Admin-Role: super-admin` |
| `GET` | `/api/passengers/` | List passengers or create demo passenger | None |

---

## 4. How to Run the Automated Test Suite

From the `backend/` directory:

```bash
cd backend
.\venv\Scripts\Activate.ps1

# Run full pytest suite (28 tests covering Steps 4 - 8)
pytest

# Run the live 12-checks Neon integration script against the running server
python tests/test_step8_live_e2e.py
```

---

## 5. Manual End-to-End Checklist (Hackathon Demo & Judging)

Use this step-by-step checklist during the hackathon evaluation against the live frontend:

1. **Search Route / Date:** Enter Origin `DXB`, Destination `LHR` -> Confirm search results match current inventory.
2. **Create Booking:** Select flight, choose seats -> Confirm booking succeeds and seat inventory decrements.
3. **Idempotency Protection:** Click "Retry Same Key" -> Confirm no duplicate booking and no double inventory decrement.
4. **Lookup Booking:** Open "My Booking", search by Booking ID -> Confirm details, class, and status match.
5. **Cancel Booking:** Click "Cancel Booking" -> Confirm status updates (`CANCELLED_...`) and seat inventory is restored.
6. **Waitlist Validation (Seats Available):** Attempt to join waitlist on a flight with seats > 0 -> Confirm 400 Bad Request rejection.
7. **Waitlist Full Join:** Book all seats in a class to 0, then join waitlist -> Confirm success and entry appears in queue.
8. **Admin Flight Creation:** Switch to "Admin Panel" (`super-admin`), create a new flight -> Confirm it appears in search results.
9. **Admin Schedule Shift:** Edit flight schedule by >= 60 minutes -> Confirm active bookings get `schedule_change_override = true`.
10. **Admin Flight Cancellation:** As `super-admin`, cancel flight -> Confirm all active bookings cascade to `CANCELLED_REFUNDED`.
11. **Role Gating Security:** Switch role header to `ops-agent`, attempt to cancel a flight -> Confirm rejected with 403 Forbidden.
12. **Neon Audit Trail:** Click "Refresh Audit Logs" in Admin Panel -> Confirm audit entries exist in Neon for every action.
