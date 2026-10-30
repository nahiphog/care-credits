"""Request-bounded scraper runtime. No database imports or credentials are required."""
import os
import secrets
import time
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from scraper.extraction import configuration, ExtractionError
from scraper.worker import run_job
from shared.discovery_limits import SCRAPER_EXECUTION_SECONDS

app = FastAPI(title='Care Credits discovery service')


def authorized(request: Request):
    token = (os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()
    if not token or not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
        raise HTTPException(401, 'Worker authorization required.')


class DiscoveryRun(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=3, max_length=300)
    max_results: int = Field(ge=1, le=1, strict=True)
    lease_token: str = Field(min_length=1, max_length=200)
    expires_at: float = Field(gt=0, allow_inf_nan=False)


@app.get('/health/live')
def live():
    return {'status': 'live'}


@app.get('/health/ready')
def ready():
    try:
        configuration()
        model = True
    except ExtractionError:
        model = False
    tavily = bool((os.getenv('TAVILY_API_KEY') or '').strip())
    token = bool((os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip())
    ok = model and tavily and token
    return JSONResponse({'status': 'ready' if ok else 'not_ready', 'model_ready': model,
                         'tavily_configured': tavily}, status_code=200 if ok else 503)


@app.post('/internal/v1/discovery/run', dependencies=[Depends(authorized)])
def execute(body: DiscoveryRun):
    # The authenticated backend already claimed the job. This fixed ticket cannot
    # extend that lease, and does not require a circular scraper -> backend binding.
    remaining = body.expires_at - time.time()
    if remaining <= 0:
        raise HTTPException(409, 'Discovery lease has expired.')
    deadline = time.monotonic() + min(SCRAPER_EXECUTION_SECONDS, remaining)

    def check_deadline():
        if time.monotonic() >= deadline or time.time() >= body.expires_at:
            raise ExtractionError('Discovery deadline reached.')

    try:
        check_deadline()
        result = run_job(body.model_dump(), check_deadline, review_only=True)
        check_deadline()
        return result
    except ExtractionError as exc:
        raise HTTPException(409, 'Discovery stopped because its lease or execution window expired.') from exc
