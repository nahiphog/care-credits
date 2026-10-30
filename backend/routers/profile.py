"""Profile HTTP endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from security import current_user
from schemas.account import ProfileChange
from serializers.common import profile
from services.profile_service import change_profile as save_profile
from services.audit_service import list_audit

router = APIRouter(prefix='/api/v1/me', tags=['profile'])

@router.get('')
def me(user=Depends(current_user)):
    return profile(user)

@router.patch('')
def change_profile(body: ProfileChange, user=Depends(current_user), db: Session = Depends(get_db)):
    return save_profile(db, user, body.model_dump())

@router.get('/audit')
def my_audit(page: int = 1, page_size: int = 20, user=Depends(current_user), db: Session = Depends(get_db)):
    return list_audit(db, page, page_size, account_id=user.id)
