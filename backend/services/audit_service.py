"""Audit visibility and pagination policy."""
from domain.errors import DomainError
from repository.audit_repository import paginated
from serializers.common import audit_json

def list_audit(db, page=1, page_size=20, account_id=None):
    if page < 1 or not 1 <= page_size <= 50:
        raise DomainError(422, 'Invalid pagination.')
    rows, total = paginated(db, page, page_size, account_id)
    return {'items': [audit_json(row) for row in rows], 'total':total, 'page':page, 'page_size':page_size}
