"""Infrastructure health and public capability endpoints."""
import os
from fastapi import APIRouter, Depends
from database import get_db
from domain.config import digest_available
from repository.health_repository import readiness
from oauth import configured as google_oauth
router = APIRouter(tags=['public'])
@router.get('/health')
def health(): return {'status': 'ok'}
@router.get('/health/live')
def live(): return {'status': 'live'}
@router.get('/health/ready')
def ready(db=Depends(get_db)): return readiness(db)
@router.get('/api/v1/config')
def config():
    return {'demo': os.getenv('DEMO_MODE') == 'true', 'signup_enabled': os.getenv('ALLOW_SIGNUP') == 'true',
            'oauth_google': google_oauth(), 'discovery_max_results': 1 if os.getenv('SERVERLESS_MODE') == 'true' else 5,
            'digest_available': digest_available(), 'password_change_available': True,
            'default_timezone': os.getenv('DEFAULT_TIMEZONE', 'Asia/Kuala_Lumpur')}
