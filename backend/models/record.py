"""Passive ORM mappings for record storage."""
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON, ForeignKey, UniqueConstraint
from database import Base
from .common import uid
import time


class Record(Base):
    __tablename__ = 'doctor_records'
    __table_args__ = (UniqueConstraint('account_id', 'course_id'),)
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    course_id = Column(String, ForeignKey('courses.id'), nullable=False)
    signed_up = Column(Boolean, default=False, nullable=False)
    signup_status = Column(String, default='not_recorded', nullable=False)
    attended = Column(Boolean, default=False, nullable=False)
    attendance_status = Column(String, default='not_recorded', nullable=False)
    attended_on = Column(String, nullable=True)
    points = Column(Float, nullable=True)
    credit_label = Column(String, default='CPD', nullable=False)
    notes = Column(String, default='', nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    signed_up_at = Column(Float, nullable=True)
    points_origin = Column(String, default='', nullable=False)



class RecordHistory(Base):
    __tablename__ = 'record_history'
    id = Column(String, primary_key=True, default=uid)
    record_id = Column(String, ForeignKey('doctor_records.id'), nullable=False, index=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    changed = Column(JSON, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)

