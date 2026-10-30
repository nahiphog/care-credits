"""HTTP request validation for learning records and preferences."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class RecordChange(BaseModel):
    signed_up: bool = False
    signup_status: Literal['not_recorded', 'signed_up', 'cancelled'] | None = None
    attended: bool = False
    attendance_status: Literal['not_recorded', 'attended'] | None = None
    attended_on: date | None = None
    points: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    credit_label: str = Field(default='CPD', min_length=1, max_length=30)
    notes: str = Field(default='', max_length=5000)
    public: bool = False
    version: int = Field(default=0, ge=0)

    @field_validator('points', mode='before')
    @classmethod
    def points_reject_bool(cls, value):
        # JSON true/false must not become 1.0/0.0 recorded CPD (parity with Jev/usage bool reject).
        if isinstance(value, bool):
            raise ValueError('Points must be a number.')
        return value


class DigestChange(BaseModel):
    opted_in: bool
    # Omit to keep the stored cadence; defaulting to 14 would wipe a custom NTF-01 preference.
    cadence_days: int | None = Field(default=None, ge=7, le=60)


class CertificateIssue(BaseModel):
    # None = calendar year in Asia/Kuala_Lumpur; 0 must not coerce via `or`.
    year: int | None = Field(default=None, ge=1900, le=2200)


