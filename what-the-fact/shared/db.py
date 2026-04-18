"""SQLAlchemy engine + session factory for WTF services."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_URL = os.environ["WTF_DATABASE_URL"]  # e.g. postgresql+psycopg2://archie:***@192.168.1.200:5432/archie
engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_session():
    """FastAPI-style session generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
