from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Use an environment variable for the database URL, falling back to SQLite for local dev
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./carecredit.db"
)

# SQLite requires this argument when used with async/multi-threaded contexts
connect_args = (
    {"check_same_thread": False}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Dependency for getting a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
