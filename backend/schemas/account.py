"""HTTP request validation for accounts and profiles."""
from pydantic import BaseModel, Field, field_validator, model_validator

def _display_name(value: str) -> str:
    cleaned = (value or '').strip()
    if len(cleaned) < 2 or len(cleaned) > 100:
        raise ValueError('Enter a display name of 2–100 characters.')
    return cleaned


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(default='Doctor', min_length=1, max_length=120)

    @field_validator('email')
    @classmethod
    def email_check(cls, value):
        value = value.strip().lower()
        if '@' not in value or '.' not in value.split('@')[-1] or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address')
        return value

    @field_validator('name')
    @classmethod
    def name_check(cls, value):
        return _display_name(value)


class ProfileChange(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(max_length=100)
    state: str = Field(default='', max_length=100)
    bio: str = Field(max_length=1000)
    public_enabled: bool
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @field_validator('name')
    @classmethod
    def name_check(cls, value):
        return _display_name(value)

    @field_validator('city', 'state', 'bio')
    @classmethod
    def trim_text(cls, value):
        return (value or '').strip() if isinstance(value, str) else value

    @field_validator('latitude', 'longitude', mode='before')
    @classmethod
    def coordinates_reject_bool(cls, value):
        # JSON true/false must not become 1.0/0.0 near-me coordinates (parity with Training coords).
        if isinstance(value, bool):
            raise ValueError('Coordinates must be numbers.')
        return value

    @model_validator(mode='after')
    def coordinates_together(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Latitude and longitude must be supplied together.')
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


