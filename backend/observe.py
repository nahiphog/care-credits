"""Sanitized request/job logs. Never log secrets, notes, or identity tokens."""
from __future__ import annotations

import logging
import math

log = logging.getLogger('carecredits')


def setup():
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def normalize_job_usage(usage) -> dict:
    """Store/log provider-reported usage only; unknown values stay null (never invent spend)."""
    payload = usage if isinstance(usage, dict) else {}

    def nonneg(raw, as_int=False):
        # Reject bools: int(True)==1 / float(False)==0.0 would invent spend from junk JSON.
        if raw is None or raw == '' or isinstance(raw, bool):
            return None
        # Reject non-finite floats before int(): int(inf) raises OverflowError (not ValueError).
        if isinstance(raw, float) and not math.isfinite(raw):
            return None
        try:
            value = int(raw) if as_int else float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        # Reject NaN/inf so partial jobs cannot surface invented infinite spend.
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if value < 0:
            return None
        return value

    result = {
        'tavily_credits': nonneg(payload.get('tavily_credits')),
        'model_tokens': nonneg(payload.get('model_tokens'), as_int=True),
    }
    if 'catalogue_saved' in payload:
        saved = nonneg(payload.get('catalogue_saved'), as_int=True)
        if saved is not None:
            result['catalogue_saved'] = saved
    return result


def request_line(request_id: str, method: str, path: str, status: int, duration_ms: int):
    log.info(
        'request id=%s method=%s path=%s status=%s duration_ms=%s',
        request_id,
        method,
        path,
        status,
        duration_ms,
    )


def failure_line(request_id: str, status: int, message: str):
    (log.error if status >= 500 else log.warning)('failure id=%s status=%s message=%s', request_id, status, str(message)[:200])


def job_line(job_id: str, status: str, candidate_count: int, source_count: int, usage, warning_count: int):
    usage = normalize_job_usage(usage)
    log.info(
        'job id=%s status=%s candidates=%s sources=%s tavily_credits=%s model_tokens=%s warnings=%s',
        job_id,
        status,
        candidate_count,
        source_count,
        usage.get('tavily_credits'),
        usage.get('model_tokens'),
        warning_count,
    )
