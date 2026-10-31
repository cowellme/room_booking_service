from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings
from .booking_constraints import database_conflict_detail

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except DBAPIError as exc:
        db.rollback()
        if detail := database_conflict_detail(exc):
            raise HTTPException(409, detail) from exc
        raise
    finally:
        db.close()
