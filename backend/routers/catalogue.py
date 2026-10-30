from datetime import date
from typing import Literal
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from database import get_db
from security import current_user, operator, worker
from schemas.discovery import NewJob, Review, CompleteJob, CatalogueLookup, CatalogueDecide, CatalogueSave
from services import catalogue_service as service

def trainings(q: str='', city: str='', state: str='', mode: str='', difficulty: str='', verification_status: str='', publication_status: str='', max_fee: float | None=None, max_fee_myr: float | None=None, min_points: float | None=None, period: Literal['upcoming', 'past', 'all']='upcoming', date_from: date | None=None, date_to: date | None=None, include_unknown: bool=False, latitude: float | None=None, longitude: float | None=None, radius_km: int | None=None, page: int=1, page_size: int=20, user=Depends(current_user), db: Session=Depends(get_db)):
    return service.trainings(q=q, city=city, state=state, mode=mode, difficulty=difficulty, verification_status=verification_status, publication_status=publication_status, max_fee=max_fee, max_fee_myr=max_fee_myr, min_points=min_points, period=period, date_from=date_from, date_to=date_to, include_unknown=include_unknown, latitude=latitude, longitude=longitude, radius_km=radius_km, page=page, page_size=page_size, user=user, db=db)

def detail(course_id: str, user=Depends(current_user), db: Session=Depends(get_db)):
    return service.detail(course_id=course_id, user=user, db=db)

def register(app):
    router = APIRouter(tags=['catalogue'])
    router.add_api_route('/api/v1/trainings', trainings, methods=['GET'])
    router.add_api_route('/api/v1/trainings/{course_id}', detail, methods=['GET'])
    app.include_router(router)
