"""Passive ORM mappings for session storage."""
from sqlalchemy import Column, String, Float, ForeignKey
from database import Base


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    expires_at = Column(Float, nullable=False)

