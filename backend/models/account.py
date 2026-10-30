"""Account authentication identity plus temporary profile-attribute compatibility."""
from sqlalchemy import Column, String, Float, Boolean, UniqueConstraint
from database import Base
from .common import uid
import time


from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import case, select
from .profile import AccountProfile, PROFILE_DEFAULTS

class Account(Base):
    __tablename__ = 'accounts'
    __table_args__ = (UniqueConstraint('identity_issuer', 'identity_subject'),)
    id = Column(String, primary_key=True, default=uid)
    email = Column(String, unique=True, nullable=False)
    _legacy_name = Column('name', String, nullable=False)
    password_hash = Column(String, nullable=False)
    _legacy_city = Column('city', String, default='Kuala Lumpur', nullable=False)
    _legacy_state = Column('state', String, default='', nullable=False)
    _legacy_latitude = Column('latitude', Float, nullable=True)
    _legacy_longitude = Column('longitude', Float, nullable=True)
    _legacy_location_consent_at = Column('location_consent_at', Float, nullable=True)
    identity_issuer = Column(String, nullable=True)
    identity_subject = Column(String, nullable=True)
    role = Column(String, default='doctor', nullable=False)
    _legacy_public_enabled = Column('public_enabled', Boolean, default=False, nullable=False)
    _legacy_public_slug = Column('public_slug', String, unique=True, default=uid, nullable=False)
    _legacy_bio = Column('bio', String, default='', nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)

    profile_record = relationship('AccountProfile', uselist=False, lazy='joined',
                                  cascade='all, delete-orphan', single_parent=True)

    def ensure_profile(self):
        """Storage compatibility during migration; profile is authoritative when present."""
        if self.profile_record is None:
            values = {}
            for field, default in PROFILE_DEFAULTS.items():
                value = getattr(self, '_legacy_' + field)
                if value is None and default is not None:
                    value = default() if callable(default) else default
                values[field] = value
                setattr(self, '_legacy_' + field, value)
            self.profile_record = AccountProfile(**values)
        return self.profile_record


def _profile_attribute(field):
    def getter(self):
        profile = self.profile_record
        return getattr(profile, field) if profile is not None else getattr(self, '_legacy_' + field)

    def setter(self, value):
        setattr(self.ensure_profile(), field, value)
        # Transitional dual-write preserves rollback to pre-profile application code.
        setattr(self, '_legacy_' + field, value)

    def expression(cls):
        present = select(AccountProfile.account_id).where(AccountProfile.account_id == cls.id).correlate(cls).exists()
        value = select(getattr(AccountProfile, field)).where(AccountProfile.account_id == cls.id).correlate(cls).scalar_subquery()
        return case((present, value), else_=getattr(cls, '_legacy_' + field))

    return hybrid_property(getter, setter, expr=expression)


for _field in PROFILE_DEFAULTS:
    setattr(Account, _field, _profile_attribute(_field))
