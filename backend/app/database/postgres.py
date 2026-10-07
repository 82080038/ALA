"""
PostgreSQL connection — Transactional data, Audit Logs, Case Management.

Uses a synchronous SQLAlchemy engine (psycopg2). Engine creation is lazy —
no connection is opened until the first query, so importing this module is
safe even when the database is not yet reachable.
Tables are created empty (no pre-loaded data). Full ORM models: Phase 2.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.database_url, echo=settings.db_echo)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency injection for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
