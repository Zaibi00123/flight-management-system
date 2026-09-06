import sys
import os

# Ensure backend directory is in sys.path so running from any directory works
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import engine, Base, get_db
import models
from routers import flights, passengers, bookings, waitlist, search, admin
from sqlalchemy import text
from sqlalchemy.orm import Session


# Create database tables if they do not exist
Base.metadata.create_all(bind=engine)

# Non-destructive additive column migration for existing databases
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE bookings ADD COLUMN schedule_change_override BOOLEAN DEFAULT 0"))
        conn.commit()
    except Exception:
        pass

app = FastAPI(title="Flight Management System API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with appropriate prefixes
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(flights.router, prefix="/api/flights", tags=["flights"])
app.include_router(passengers.router, prefix="/api/passengers", tags=["passengers"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])
app.include_router(waitlist.router, prefix="/api/waitlist", tags=["waitlist"])

# Serve frontend static assets if directory exists
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_root():
    frontend_index = os.path.join(frontend_dir, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    return {"message": "Flight Management System API"}

@app.get("/app")
def read_app():
    frontend_index = os.path.join(frontend_dir, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    return {"message": "Frontend not found"}

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        dialect = engine.dialect.name
        return {
            "status": "ok",
            "database": "connected",
            "dialect": dialect,
            "backend": "Neon PostgreSQL" if dialect == "postgresql" else dialect,
        }
    except Exception as e:
        return {"status": "error", "database": str(e)}

