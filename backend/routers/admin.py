from datetime import date
from typing import Literal
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from database import get_db
from security import current_user, operator, worker
from schemas.discovery import NewJob, Review, CompleteJob, CatalogueLookup, CatalogueDecide, CatalogueSave
from services import discovery_status_service
from services import ingestion_job_service
from services import candidate_review_service
from services import ingestion_completion_service
from services import catalogue_connect_service

def services(user=Depends(operator), db: Session=Depends(get_db)):
    return discovery_status_service.services(user=user, db=db)

def integrations(user=Depends(operator)):
    return discovery_status_service.integrations(user=user)

def create_job(body: NewJob, request: Request, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.create_job(body=SimpleNamespace(**body.model_dump(mode='json')), request_key=request.headers.get('Idempotency-Key', ''), user=user, db=db)

def run_serverless_job(job_id: str, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.run_serverless_job(job_id=job_id, user=user, db=db)

def jobs(page: int=1, page_size: int=20, status: str | None=None, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.jobs(page=page, page_size=page_size, status=status, user=user, db=db)

def job_detail(job_id: str, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.job_detail(job_id=job_id, user=user, db=db)

def retry_job(job_id: str, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.retry_job(job_id=job_id, user=user, db=db)

def candidates(page: int=1, page_size: int=20, status: str | None=None, job_id: str | None=None, user=Depends(operator), db: Session=Depends(get_db)):
    return candidate_review_service.candidates(page=page, page_size=page_size, status=status, job_id=job_id, user=user, db=db)

def review(candidate_id: str, body: Review, user=Depends(operator), db: Session=Depends(get_db)):
    return candidate_review_service.review(candidate_id=candidate_id, body=SimpleNamespace(**body.model_dump(mode='json')), user=user, db=db)

def cancel_training(course_id: str, user=Depends(operator), db: Session=Depends(get_db)):
    return candidate_review_service.cancel_training(course_id=course_id, user=user, db=db)

def scrape_topics(user=Depends(operator)):
    return ingestion_job_service.scrape_topics(user=user)

def trigger_daily_scrape(force: bool=False, user=Depends(operator), db: Session=Depends(get_db)):
    return ingestion_job_service.trigger_daily_scrape(force=force, user=user, db=db)

def register(app):
    router = APIRouter(tags=['admin'])
    router.add_api_route('/api/v1/admin/services', services, methods=['GET'])
    router.add_api_route('/api/v1/admin/integrations', integrations, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs', create_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}/run', run_serverless_job, methods=['POST'])
    router.add_api_route('/api/v1/admin/ingestion-jobs', jobs, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}', job_detail, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}/retry', retry_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/v1/admin/candidates', candidates, methods=['GET'])
    router.add_api_route('/api/v1/admin/candidates/{candidate_id}/review', review, methods=['POST'])
    router.add_api_route('/api/v1/admin/trainings/{course_id}/cancel', cancel_training, methods=['POST'])
    router.add_api_route('/api/v1/admin/scrape-topics', scrape_topics, methods=['GET'])
    router.add_api_route('/api/v1/admin/daily-scrape', trigger_daily_scrape, methods=['POST'], status_code=202)
    app.include_router(router)
