"""Application composition: HTTP boundaries, lifecycle and feature routers."""
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from domain.errors import DomainError
from errors import envelope, http_exception_handler, validation_exception_handler
from http_boundary import request_boundary
from lifecycle import lifespan
from observe import setup
from routers import (auth, profile, records, certificates, exports, public_profiles,
                     preferences, health, operations, catalogue, admin, internal)

setup()
app = FastAPI(title='CareCredits', version='0.6.0', lifespan=lifespan)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

@app.exception_handler(DomainError)
async def domain_error(request, exc):
    return envelope(exc.status_code, exc.detail, request)

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return envelope(500, 'Request failed.', request)

app.middleware('http')(request_boundary)
for feature in (auth, profile, records, certificates, exports, public_profiles,
                preferences, health, operations):
    app.include_router(feature.router)
for feature in (catalogue, admin, internal):
    feature.register(app)
