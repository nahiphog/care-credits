import hashlib
import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo
import ipaddress
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


# All middle-layer week keys are evaluated in Malaysian local time so the Monday–Sunday
# window a scrape belongs to never drifts with the server's UTC wall clock.
KL_TZ = ZoneInfo('Asia/Kuala_Lumpur')

WEEK_KEY_PATTERN = r'^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$'
_WEEK_KEY_RE = re.compile(WEEK_KEY_PATTERN)

# Query parameters that only carry campaign/click attribution. Stripping them lets the same
# resource dedupe to one canonical URL and one source_key across topics within a week.
TRACKING_PARAMS = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_reader', 'utm_name', 'utm_social', 'utm_social-type',
    'fbclid', 'gclid', 'dclid', 'gclsrc', 'msclkid', 'yclid', 'twclid',
    'igshid', 'mc_cid', 'mc_eid', 'ref', 'ref_src', 'ref_url', 'spm',
    'vero_id', 'vero_conv', '_hsenc', '_hsmi', 'oly_anon_id', 'oly_enc_id',
})


def web_url(value):
    if not value:
        return value
    try:
        p = urlsplit(value)
        host = p.hostname or ''
        if p.scheme not in ('https', 'http') or '.' not in host or p.username or p.password or p.port not in (None, 80, 443) or host.endswith(('.local', '.localhost', '.internal')):
            raise ValueError('A public web URL is required')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return value
        raise ValueError('Literal IP addresses are not allowed')
    except Exception:
        raise ValueError('A public web URL is required') from None


def public_web_url(value):
    if not value:
        return None
    try:
        return web_url(value)
    except ValueError:
        return None


def canonical_web_url(value):
    """Return an SSRF-safe, deduplication-ready canonical form of ``value`` or ``None``.

    Reuses ``web_url`` for literal-IP / loopback / credential rejection, then lowercases the
    scheme and host, drops the fragment and tracking query parameters, and normalizes a
    trailing path slash so links that differ only by ``#anchor`` or ``utm_*`` collapse to one key.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        web_url(value)
    except ValueError:
        return None
    parts = urlsplit(value)
    path = parts.path or ''
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')
    kept = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS]
    query = urlencode(kept)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ''))


def compute_source_key(source_url, title, start_date=None):
    """Deterministic catalogue identity key.

    Mirrors the backend ``catalogue.source_key`` / ``digest`` formula exactly
    (``sha256(url_without_fragment | lower(title) | str(start_date))``) so the scraper and the
    ``/internal/v1/ingestion`` contract agree on ``source_key`` without a round trip.
    """
    base = (source_url or '').split('#')[0]
    raw = base + '|' + (title or '').strip().lower() + '|' + str(start_date)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _coerce_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def week_key_for_date(value, fallback_today=None):
    """ISO ``YYYY-Www`` week key in ``Asia/Kuala_Lumpur``.

    Parses ``date`` objects or ``YYYY-MM-DD`` strings; when ``value`` has no usable date the key
    falls back to ``fallback_today`` or the current Malaysian week (the active scrape window).
    """
    resolved = _coerce_date(value)
    if resolved is None:
        resolved = _coerce_date(fallback_today) or datetime.now(KL_TZ).date()
    iso_year, iso_week, _ = resolved.isocalendar()
    return f'{iso_year:04d}-W{iso_week:02d}'


def week_window(week_key):
    """Return ``(monday_iso, sunday_iso)`` for a ``YYYY-Www`` key."""
    match = _WEEK_KEY_RE.match(week_key or '')
    if not match:
        raise ValueError('A valid YYYY-Www week_key is required')
    iso_year, iso_week = int(week_key[:4]), int(week_key[6:])
    try:
        monday = date.fromisocalendar(iso_year, iso_week, 1)
        sunday = date.fromisocalendar(iso_year, iso_week, 7)
    except ValueError as exc:
        raise ValueError('A valid YYYY-Www week_key is required') from exc
    return (monday.isoformat(), sunday.isoformat())


def ensure_week_key_first(mapping, week_key):
    """Guarantee ``mapping`` is partitioned at ``week_key`` first and return that week bucket."""
    if not isinstance(mapping, dict):
        raise TypeError('ensure_week_key_first requires a dict mapping')
    if not _WEEK_KEY_RE.match(week_key or ''):
        raise ValueError('A valid YYYY-Www week_key is required')
    window_start, window_end = week_window(week_key)
    bucket = mapping.setdefault(week_key, {})
    bucket.setdefault('week_key', week_key)
    bucket.setdefault('window_start', window_start)
    bucket.setdefault('window_end', window_end)
    return bucket


class Training(BaseModel):
    model_config = ConfigDict(extra='forbid', protected_namespaces=())
    title: str = Field(min_length=3, max_length=200)
    provider: str = Field(min_length=2, max_length=200)
    description: str = Field(max_length=3000, default='')
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=80)
    venue: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: Literal['MY'] = 'MY'
    mode: Literal['in_person', 'online', 'hybrid']
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    fee: float | None = Field(default=None, ge=0, le=1000000, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    points: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    credit_label: str | None = Field(default=None, max_length=30)
    difficulty: Literal['beginner', 'intermediate', 'advanced'] | None = None
    prerequisites: str | None = Field(default=None, max_length=2000)
    registration_url: str | None = Field(default=None, max_length=2000)
    source_url: str = Field(max_length=2000)
    evidence: dict[str, str] = Field(default_factory=dict)
    source_text: str = Field(max_length=50000, default='')
    model_id: str | None = None
    retrieved_at: str | None = None
    model_weights_url: str | None = None
    model_license_url: str | None = None
    model_publisher: str | None = Field(default=None, max_length=200)
    model_host: str | None = Field(default=None, max_length=200)
    # Week-key-first index fields: auto-populated below so every candidate is bucketed by its
    # event week first and carries the ingestion-contract source_key.
    week_key: str | None = Field(default=None, pattern=WEEK_KEY_PATTERN)
    scrape_week_key: str | None = Field(default=None, pattern=WEEK_KEY_PATTERN)
    source_key: str | None = Field(default=None, min_length=16, max_length=200)

    @field_validator('latitude', 'longitude', 'fee', 'points', mode='before')
    @classmethod
    def reject_bool_numbers(cls, value):
        # JSON true/false must not become 1.0/0.0 fee/points/coords (parity with Jev/usage bool reject).
        if isinstance(value, bool):
            raise ValueError('Numeric fields must be numbers, not booleans')
        return value

    @field_validator('source_url', 'registration_url', 'model_weights_url', 'model_license_url')
    @classmethod
    def urls(cls, value):
        return web_url(value)

    @model_validator(mode='after')
    def constraints(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Supply both coordinates or neither')
        if self.fee is not None and not self.currency:
            raise ValueError('Known fees need a currency')
        if self.mode != 'online' and not self.city:
            raise ValueError('In-person sessions need a city')
        if self.points is not None and not self.credit_label:
            raise ValueError('Known points need their original credit label')
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError('End date cannot be before start date')
        if len(self.evidence) > 30 or any(len(v) > 2000 for v in self.evidence.values()):
            raise ValueError('Evidence is too large')
        # Always index at the week_key first: event week from start_date, else the scrape week.
        if self.scrape_week_key is None:
            self.scrape_week_key = week_key_for_date(None)
        if self.week_key is None:
            if self.start_date is not None:
                self.week_key = week_key_for_date(self.start_date)
            else:
                self.week_key = self.scrape_week_key or week_key_for_date(None)
        if self.source_key is None:
            self.source_key = compute_source_key(self.source_url, self.title, self.start_date)
        return self


def validate_evidence(training):
    required = ['title', 'provider', 'country', 'mode']
    required += [key for key in ('start_date', 'end_date', 'timezone', 'venue', 'city', 'state', 'fee', 'currency', 'points', 'credit_label', 'difficulty', 'prerequisites', 'registration_url') if getattr(training, key) is not None]
    # Verbatim match stays strict; the normalized fallback only forgives collapsed whitespace
    # (\r\n, \u00a0, repeated spaces) from HTML-to-text so no invented tokens can slip through.
    normalized_text = ' '.join(training.source_text.split())
    for field in required:
        quote = training.evidence.get(field, '')
        if not quote.strip():
            raise ValueError('Missing source evidence for ' + field)
        if quote in training.source_text:
            continue
        normalized_quote = ' '.join(quote.split())
        if normalized_quote and normalized_quote in normalized_text:
            continue
        raise ValueError('Missing source evidence for ' + field)
    # Coordinates are not model-inferred; geocoding is not part of this extraction contract.
    if training.latitude is not None or training.longitude is not None:
        raise ValueError('Extracted coordinates require a separate verified geocoding step')
    return training
