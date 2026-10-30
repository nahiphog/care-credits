"""Passive ORM mappings for digest storage."""
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON, ForeignKey
from database import Base
from .common import uid
import time


class DigestPreference(Base):
    __tablename__ = 'digest_preferences'
    account_id = Column(String, ForeignKey('accounts.id'), primary_key=True)
    opted_in = Column(Boolean, default=False, nullable=False)
    cadence_days = Column(Integer, default=14, nullable=False)
    last_sent_at = Column(Float, nullable=True)
    unsubscribed_at = Column(Float, nullable=True)
    unsubscribe_token = Column(String, unique=True, default=uid, nullable=False)
    fail_count = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(Float, nullable=True)



class DigestSend(Base):
    __tablename__ = 'digest_sends'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    sent_at = Column(Float, default=time.time, nullable=False)
    status = Column(String, default='queued', nullable=False)
    event_count = Column(Integer, default=0, nullable=False)
    recorded_points_snapshot = Column(Float, default=0, nullable=False)
    provider_message_id = Column(String, nullable=True)
    error = Column(String, default='', nullable=False)
    payload = Column(JSON, nullable=True)

