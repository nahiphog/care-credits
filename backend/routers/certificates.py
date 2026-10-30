"""Certificate HTTP routes; rendering and integrity rules belong to the service."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from database import get_db
from security import current_user
from schemas.learning import CertificateIssue
from services import certificate_service

router = APIRouter(prefix='/api/v1/me/certificates', tags=['certificates'])

@router.post('', status_code=201)
def create_certificate(body: CertificateIssue, user=Depends(current_user), db: Session = Depends(get_db)):
    return certificate_service.create_certificate(db, user, body.year)

@router.get('')
def certificate_history(year: int | None = None, page: int = 1, page_size: int = 10,
                        user=Depends(current_user), db: Session = Depends(get_db)):
    return certificate_service.certificate_history(db, user, year, page, page_size)

@router.get('/{certificate_id}')
def download_certificate(certificate_id: str, format: str = 'html', user=Depends(current_user), db: Session = Depends(get_db)):
    content, media_type, disposition = certificate_service.download_certificate(db, user, certificate_id, format)
    return Response(content, media_type=media_type, headers={'Content-Disposition': disposition})
