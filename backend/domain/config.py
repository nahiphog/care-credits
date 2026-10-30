"""Runtime capabilities and explicit timezone context."""
import os
from datetime import datetime
from contextvars import ContextVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .errors import DomainError

request_timezone = ContextVar('request_timezone', default=None)

def timezone_name():
    return request_timezone.get() or os.getenv('DEFAULT_TIMEZONE', 'Asia/Kuala_Lumpur')

def today(timezone=None):
    zone = timezone or timezone_name()
    try:
        return datetime.now(ZoneInfo(zone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError(422, 'Invalid timezone.')

def production_env() -> bool:
    """True when APP_ENV is production (strip + casefold so padding/Production still harden cookies)."""
    return (os.getenv('APP_ENV') or '').strip().casefold() == 'production'


def digest_available():
    return (os.getenv('DIGEST_ENABLED', 'true').lower() == 'true'
            and (os.getenv('SERVERLESS_MODE') != 'true' or os.getenv('SERVERLESS_DIGEST_ENABLED') == 'true')
            and (os.getenv('MAIL_PROVIDER') or 'log').strip().lower() == 'smtp'
            and bool((os.getenv('SMTP_HOST') or '').strip())
            and bool((os.getenv('SMTP_FROM') or os.getenv('SMTP_USER') or '').strip()))
