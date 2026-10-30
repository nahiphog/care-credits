"""Operator audit and private maintenance HTTP endpoints."""
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from database import get_db
from security import operator
from services.audit_service import list_audit
from services.maintenance_service import maintain, status
from services.catalogue_quality_service import queue
from http_boundary import client_host

router = APIRouter(tags=['operations'])

@router.get('/api/v1/admin/maintenance')
def maintenance_status(request: Request, user=Depends(operator), db=Depends(get_db)):
    client_host(request)
    return {**status(db), 'client_identity_verified': bool(getattr(request.state, 'client_identity_verified', False))}

@router.get('/api/v1/admin/catalogue-quality')
def catalogue_quality(page: int = 1, user=Depends(operator), db=Depends(get_db)):
    return queue(db, page)

@router.get('/api/v1/admin/audit')
def audit(page: int = 1, page_size: int = 20, user=Depends(operator), db=Depends(get_db)):
    return list_audit(db, page, page_size)

@router.get('/internal/v1/maintenance')
def maintenance(request: Request, db=Depends(get_db)):
    secret = os.getenv('CRON_SECRET', '')
    if not secret or not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + secret):
        raise HTTPException(401, 'Maintenance authorization required.')
    return maintain(db)
