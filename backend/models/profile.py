"""Canonical one-to-one public/location profile, separate from login credentials."""
from sqlalchemy import Column, String, Float, Boolean, ForeignKey
from database import Base
from .common import uid

PROFILE_DEFAULTS = {
    'name': '', 'city': 'Kuala Lumpur', 'state': '', 'latitude': None,
    'longitude': None, 'location_consent_at': None, 'public_enabled': False,
    'public_slug': uid, 'bio': '',
}


class AccountProfile(Base):
    __tablename__ = 'account_profiles'
    account_id = Column(String, ForeignKey('accounts.id', ondelete='CASCADE'), primary_key=True)
    name = Column(String, nullable=False)
    city = Column(String, default='Kuala Lumpur', nullable=False)
    state = Column(String, default='', nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_consent_at = Column(Float, nullable=True)
    public_enabled = Column(Boolean, default=False, nullable=False)
    public_slug = Column(String, unique=True, default=uid, nullable=False)
    bio = Column(String, default='', nullable=False)
