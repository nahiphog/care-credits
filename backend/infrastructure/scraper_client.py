"""Authenticated HTTP boundary to the independently deployed scraper runtime."""
import os
import httpx
from types import SimpleNamespace
from schemas.discovery import CompleteJob
from domain.errors import DomainError
from shared.discovery_limits import SCRAPER_REQUEST_TIMEOUT_SECONDS


def _base():
    return (os.getenv('SCRAPER_SERVICE_URL') or os.getenv('SCRAPER_HEALTH_URL') or '').strip().rstrip('/')


def status():
    base = _base()
    if not base:
        return {'status': 'unconfigured', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
    try:
        response = httpx.get(base + '/health/ready', timeout=3)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('Unexpected readiness response')
        return {'status': 'ready' if response.status_code == 200 and payload.get('status') == 'ready' else 'not_ready',
                'reachable': True, 'tavily_configured': bool(payload.get('tavily_configured')),
                'model_ready': bool(payload.get('model_ready'))}
    except (httpx.HTTPError, ValueError, TypeError):
        return {'status': 'unreachable', 'reachable': False, 'tavily_configured': False, 'model_ready': False}


def execute(job):
    base = _base()
    token = (os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()
    if not base or not token:
        raise DomainError(503, 'The discovery service is not configured.')
    try:
        response = httpx.post(base + '/internal/v1/discovery/run', json=job,
                              headers={'Authorization': 'Bearer ' + token}, timeout=SCRAPER_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('Unexpected discovery response')
        return SimpleNamespace(**CompleteJob.model_validate(payload).model_dump(mode="json"))
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        # Do not retry paid work: the lease expires and an operator chooses whether to retry.
        raise DomainError(503, 'Discovery did not return a confirmed result. Refresh job status before retrying.') from exc
