"""HTTP request validation for discovery and review endpoints."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from shared.contracts import Training, validate_evidence
REVIEW_FIELDS = ('title', 'provider', 'description', 'start_date', 'end_date', 'timezone', 'venue', 'city', 'state', 'mode', 'fee', 'currency', 'points', 'credit_label', 'difficulty', 'prerequisites', 'registration_url')

class NewJob(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    max_results: int = Field(default=5, ge=1, le=5)

    @field_validator('query')
    @classmethod
    def trim(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('Enter a search topic')
        return value.strip()

    @field_validator('max_results', mode='before')
    @classmethod
    def max_results_reject_bool(cls, value):
        if isinstance(value, bool):
            raise ValueError('max_results must be an integer from 1 to 5.')
        return value

class TavilySource(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field(default='', max_length=300)
    snippet: str = Field(default='', max_length=2000)
    extraction_status: str = Field(default='failed', max_length=40)
    verification_status: str = Field(default='unverified', max_length=40)
    retrieved_at: str | None = Field(default=None, max_length=80)

class ExtractionReceipt(BaseModel):
    model_config = {'protected_namespaces': ()}
    model_id: str = Field(min_length=1, max_length=200)
    endpoint_host: str = Field(pattern='^[A-Za-z0-9.-]+$', max_length=253)
    completed_at: datetime
    candidate_count: int = Field(ge=1, le=4)

class CompleteJob(BaseModel):
    extractions: list[ExtractionReceipt] = Field(default_factory=list, max_length=5)
    lease_token: str = Field(min_length=1, max_length=200)
    candidates: list[dict] = Field(default_factory=list, max_length=20)
    sources: list[TavilySource] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    status: Literal['succeeded', 'partial', 'failed']
    usage: dict = Field(default_factory=dict)

    @field_validator('candidates')
    @classmethod
    def candidates_are_trainings(cls, rows):
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Each candidate must be an object.')
            payload = {key: value for key, value in row.items() if not str(key).startswith('_')}
            validate_evidence(Training(**payload))
        return rows

    @model_validator(mode='after')
    def terminal_honesty(self):
        token = (self.lease_token or '').strip()
        if not token:
            raise ValueError('lease_token is required.')
        self.lease_token = token
        if self.status == 'failed' and self.candidates:
            raise ValueError('failed jobs cannot include candidates; use partial.')
        return self

class Review(BaseModel):
    action: Literal['publish', 'reject', 'hold']
    reason: str = Field(default='', max_length=500)
    version: int = Field(default=0, ge=0)
    corrections: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def require_hold_reason(self):
        if self.action in ('hold', 'reject') and len(self.reason.strip()) < 3:
            raise ValueError('Hold and reject require a reason of at least 3 characters.')
        extra = set(self.corrections) - set(REVIEW_FIELDS)
        if extra:
            raise ValueError('Unsupported correction fields.')
        if len(self.corrections) > 20 or len(self.evidence) > 20:
            raise ValueError('Too many corrections.')
        return self

class CatalogueLookup(BaseModel):
    candidate: Training

class CatalogueDecide(BaseModel):
    candidate: Training
    matches: list[dict] | None = Field(default=None, max_length=5)

class CatalogueSave(BaseModel):
    candidate: Training
    judgment: dict = Field(default_factory=dict)
    job_id: str | None = None
