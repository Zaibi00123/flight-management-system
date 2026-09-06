import os
from database import engine, Base
import models

def setup_db():
    print(f"Connecting to database: {engine.url}")
    print("Creating tables safely...")
    Base.metadata.create_all(bind=engine)
    print("Tables created and verified.")

if __name__ == "__main__":
    setup_db()
