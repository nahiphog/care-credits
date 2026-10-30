"""Public, opt-in profile endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from services.profile_service import public_profile as read_profile

router = APIRouter(prefix='/api/v1/public', tags=['public-profile'])

@router.get('/{slug}')
def public_profile(slug: str, db: Session = Depends(get_db)):
    return read_profile(db, slug)
