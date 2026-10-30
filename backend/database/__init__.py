"""Shared database connection and metadata registry."""
from .database import Base, engine, get_db, SessionLocal, SQLALCHEMY_DATABASE_URL
