import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Load environment variables from project root or backend folder .env
load_dotenv()

# Use the actual DATABASE_URL env var. If it is missing or still contains
# placeholder values, fall back to SQLite for local non-Neon development.
raw_database_url = os.getenv("DATABASE_URL")
placeholder_markers = ("<YOUR_PASSWORD>", "YOUR_PASSWORD", "********", "****", "placeholder", "example", "changeme")

if not raw_database_url or any(marker in raw_database_url for marker in placeholder_markers):
    SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"
else:
    SQLALCHEMY_DATABASE_URL = raw_database_url

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Basic SQLAlchemy Base
Base = declarative_base()

# Clean database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
