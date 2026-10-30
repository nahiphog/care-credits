"""Download response boundary for owner exports."""
from typing import Literal
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from database import get_db
from security import current_user
from services.export_service import export_records

router = APIRouter(prefix='/api/v1/me/export', tags=['exports'])

@router.get('/{kind}')
def export(kind: Literal['csv', 'eml'], year: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    content, media_type, filename = export_records(db, user, kind, year)
    return Response(content, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="{filename}"'})
