"""Passive ORM mappings for certificate storage."""
from sqlalchemy import Column, String, Float, Integer, ForeignKey
from database import Base
from .common import uid
import time


class AffiliationCertificate(Base):
    __tablename__ = 'affiliation_certificates'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    recorded_points_snapshot = Column(Float, nullable=False)
    issued_at = Column(Float, default=time.time, nullable=False)
    document_hash = Column(String, nullable=False)
    disclaimer_version = Column(String, default='CERT-01-v1', nullable=False)

