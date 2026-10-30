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

def claim(db: Session=Depends(get_db)):
    result = ingestion_job_service.claim(db=db)
    if '_idle_reason' in result:
        return Response(status_code=204, headers={'X-Care-Claim-Reason': result['_idle_reason']})
    return result

def heartbeat(job_id: str, body: dict, db: Session=Depends(get_db)):
    return ingestion_job_service.heartbeat(job_id=job_id, body=body, db=db)

def complete(job_id: str, body: CompleteJob, db: Session=Depends(get_db)):
    return ingestion_completion_service.complete(job_id=job_id, body=SimpleNamespace(**body.model_dump(mode='json')), db=db)

def catalogue_connect(db: Session=Depends(get_db)):
    return catalogue_connect_service.catalogue_connect(db=db)

def catalogue_lookup(body: CatalogueLookup, db: Session=Depends(get_db)):
    return catalogue_connect_service.catalogue_lookup(body=SimpleNamespace(**body.model_dump(mode='json')), db=db)

def catalogue_decide(body: CatalogueDecide, db: Session=Depends(get_db)):
    return catalogue_connect_service.catalogue_decide(body=SimpleNamespace(**body.model_dump(mode='json')), db=db)

def catalogue_save(body: CatalogueSave, db: Session=Depends(get_db)):
    return catalogue_connect_service.catalogue_save(body=SimpleNamespace(**body.model_dump(mode='json')), db=db)

def register(app):
    router = APIRouter(tags=['internal'])
    router.add_api_route('/internal/v1/jobs/claim', claim, methods=['POST'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/jobs/{job_id}/heartbeat', heartbeat, methods=['POST'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/jobs/{job_id}/complete', complete, methods=['POST'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/catalogue/connect', catalogue_connect, methods=['GET'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/catalogue/lookup', catalogue_lookup, methods=['POST'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/catalogue/decide', catalogue_decide, methods=['POST'], dependencies=[Depends(worker)])
    router.add_api_route('/internal/v1/catalogue/save', catalogue_save, methods=['POST'], dependencies=[Depends(worker)])
    app.include_router(router)
