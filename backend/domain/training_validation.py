"""Contract adapter: domain services exchange plain data, never transport models."""
from shared.contracts import Training, validate_evidence

def validate_training(payload):
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return validate_evidence(Training(**payload)).model_dump(mode='json')
