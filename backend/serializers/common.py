"""Public response mapping; no queries, transactions or workflow decisions."""
import os
from models import Audit
from repository.model_helpers import FILTER_FIELDS
from shared.contracts import public_web_url
from observe import normalize_job_usage

def profile(account):
    return {k: getattr(account, k) for k in ('id', 'email', 'name', 'city', 'state', 'latitude', 'longitude', 'location_consent_at', 'created_at', 'role', 'bio', 'public_enabled', 'public_slug')}


def record_json(record):
    if not record:
        return None
    return {
        k: getattr(record, k)
        for k in (
            'signed_up', 'signup_status', 'signed_up_at', 'attended', 'attendance_status', 'attended_on',
            'points', 'points_origin', 'credit_label', 'notes', 'public', 'version',
        )
    }


def public_source_payload(item):
    data = item.model_dump() if hasattr(item, 'model_dump') else dict(item)
    data['url'] = public_web_url(data.get('url'))
    return data


def job_json(job):
    result = job.result
    if isinstance(result, dict):
        result = dict(result)
        result['sources'] = [public_source_payload(item) for item in result.get('sources') or [] if isinstance(item, dict)]
        # Re-normalize stored usage so older dirty rows cannot invent spend in the UI/logs.
        if 'usage' in result:
            result['usage'] = normalize_job_usage(result.get('usage'))
    return {
        'id': job.id,
        # SDD Â§10 names the 202 field job_id; keep id for existing clients.
        'job_id': job.id,
        'query': job.query,
        'status': job.status,
        'created_at': job.created_at,
        'max_results': job.max_results,
        'attempt': job.attempt,
        'execution_mode': 'request' if os.getenv('SERVERLESS_MODE') == 'true' else 'worker',
        'result': result,
    }


def course_json(course, record=None, field_evidence=None):
    # Full source text and model configuration stay in operator review only.
    data = {k: v for k, v in (course.data or {}).items() if k not in ('source_text', 'model_weights_url', 'model_license_url')}
    for field in FILTER_FIELDS:
        data[field] = getattr(course, field)
    data['source_url'] = public_web_url(data.get('source_url'))
    data['registration_url'] = public_web_url(data.get('registration_url'))
    evidence_rows = []
    if field_evidence is not None:
        evidence_rows = [
            {'field_name': row.field_name, 'excerpt': row.excerpt, 'reviewed_at': row.reviewed_at}
            for row in field_evidence
        ]
    return {
        'id': course.id,
        **data,
        'demo': course.demo,
        'verification_status': course.verification_status or 'unverified',
        'publication_status': course.publication_status or 'published',
        'cancellation_status': course.cancellation_status or 'active',
        'reviewed_at': course.reviewed_at,
        'field_evidence': evidence_rows,
        'record': record_json(record),
    }


AUDIT_HIDDEN = {'notes', 'password', 'password_hash', 'token', 'secret', 'api_key'}


def audit_json(row: Audit) -> dict:
    changed = row.changed if isinstance(row.changed, dict) else {}
    return {
        'id': row.id,
        'action': row.action,
        'entity_id': row.entity_id,
        'changed': {key: value for key, value in changed.items() if key not in AUDIT_HIDDEN},
        'at': row.created_at,
    }
