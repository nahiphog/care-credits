"""Passive ORM mappings for audit storage."""
from sqlalchemy import Column, String, Float, Integer, JSON
from database import Base
from .common import uid
import time


class Audit(Base):
    __tablename__ = 'portal_audit'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    changed = Column(JSON, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)



class Throttle(Base):
    __tablename__ = 'request_throttle'
    key = Column(String, primary_key=True)
    count = Column(Integer, default=0, nullable=False)

