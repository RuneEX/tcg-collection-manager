from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite-Datenbank für das Projekt
DATABASE_URL = "sqlite:///./tcg.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)

# Basisklasse für alle ORM-Modelle
Base = declarative_base()


# FastAPI-Dependency für eine Datenbank-Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
