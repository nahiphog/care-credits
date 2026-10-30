"""Cross-cutting HTTP boundary; domain modules do not import this module."""
import os, secrets, time, traceback
from fastapi import Request
from errors import envelope, request_id
from observe import request_line, log as app_log
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from domain.config import request_timezone

def client_host(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return 'unknown'


DEFAULT_ALLOWED_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:3010,http://127.0.0.1:3010,http://localhost:3020,http://127.0.0.1:3020,http://localhost:3021,http://127.0.0.1:3021,http://localhost:3030,http://127.0.0.1:3030,http://localhost:3040,http://127.0.0.1:3040'


def normalize_origin(value: str | None) -> str:
    """Strip whitespace/trailing slash; opaque browser Origin `null` stays rejected.

    Scheme and host are case-insensitive (RFC 6454), so allowlist comparison casefolds.
    """
    cleaned = (value or '').strip().rstrip('/')
    if not cleaned or cleaned.casefold() == 'null':
        return ''
    return cleaned.casefold()


def origin_allowed(origin: str | None, allowed: list[str] | set[str] | tuple[str, ...]) -> bool:
    normalized = normalize_origin(origin)
    if not normalized:
        return False
    allowlist = {normalize_origin(item) for item in allowed if normalize_origin(item)}
    return normalized in allowlist


async def request_boundary(request: Request, call_next):
    started = time.perf_counter()
    request.state.request_id = secrets.token_hex(8)
    zone = request.headers.get('x-care-timezone') or os.getenv('DEFAULT_TIMEZONE', 'Asia/Kuala_Lumpur')
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return envelope(422, 'Invalid timezone.', request)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not request.url.path.startswith('/internal/'):
        origins = [item for item in os.getenv('ALLOWED_ORIGINS', DEFAULT_ALLOWED_ORIGINS).split(',') if item.strip()]
        # Strip client header like Origin â€” padded `1` from proxies must not block real mutations.
        if (request.headers.get('x-care-client') or '').strip() != '1' or not origin_allowed(
            request.headers.get('origin'), origins
        ):
            return envelope(403, 'Request origin not allowed.', request)
    timezone_token = request_timezone.set(zone)
    try:
        result = await call_next(request)
    except Exception as exc:
        # Trace locations and exception type are useful without logging SQL params,
        # credentials, provider bodies or private notes from exception messages.
        frames = traceback.extract_tb(exc.__traceback__)
        locations = ' > '.join(f'{frame.name}:{frame.lineno}' for frame in frames[-12:])
        app_log.error('unexpected id=%s method=%s path=%s type=%s frames=%s',
                      request_id(request), request.method, request.url.path,
                      type(exc).__name__, locations)
        return envelope(500, 'Request failed.', request)
    finally:
        request_timezone.reset(timezone_token)
    result.headers['Cache-Control'] = 'no-store'
    result.headers['X-Content-Type-Options'] = 'nosniff'
    rid = request_id(request)
    result.headers['X-Request-Id'] = rid
    duration_ms = int((time.perf_counter() - started) * 1000)
    request_line(rid, request.method, request.url.path, result.status_code, duration_ms)
    return result
