"""Passive persistence for recovery tokens and operational receipts."""
import time
from sqlalchemy import Column, String, Float, JSON, ForeignKey
from database import Base
from .common import uid


class PasswordReset(Base):
    __tablename__ = 'password_reset_tokens'
    token_hash = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    expires_at = Column(Float, nullable=False, index=True)


class MaintenanceRun(Base):
    __tablename__ = 'maintenance_runs'
    id = Column(String, primary_key=True, default=uid)
    started_at = Column(Float, default=time.time, nullable=False)
    finished_at = Column(Float)
    status = Column(String, nullable=False, default='running')
    counts = Column(JSON, nullable=False, default=dict)
    error_type = Column(String)


class DigestDispatch(Base):
    __tablename__ = 'digest_dispatches'
    key = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    state = Column(String, nullable=False, default='sending')
    attempted_at = Column(Float, nullable=False)
    finished_at = Column(Float)
