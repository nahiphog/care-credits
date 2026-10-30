"""Learning-record and progress HTTP endpoints."""
from typing import Literal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from security import current_user
from schemas.learning import RecordChange
from services import records_service
from services.suggestion_service import suggestions_for

router = APIRouter(prefix='/api/v1/me', tags=['learning'])

@router.put('/trainings/{course_id}')
def save_record(course_id: str, body: RecordChange, user=Depends(current_user), db: Session = Depends(get_db)):
    return records_service.save_record(db, user, course_id, body.model_dump())

@router.get('/trainings')
def my_trainings(signup_status: Literal['not_recorded', 'signed_up', 'cancelled'] | None = None,
                 attendance_status: Literal['not_recorded', 'attended'] | None = None,
                 attended: bool | None = None, page: int = 1, page_size: int = 20,
                 user=Depends(current_user), db: Session = Depends(get_db)):
    return records_service.my_trainings(db, user, signup_status, attendance_status, attended, page, page_size)

@router.get('/trainings/{course_id}/history')
def record_history(course_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    return records_service.record_history(db, user, course_id)

@router.get('/progress')
def progress(year: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    return records_service.progress(db, user, year)

@router.get('/suggestions')
def me_suggestions(user=Depends(current_user), db: Session = Depends(get_db)):
    return suggestions_for(db, user)
