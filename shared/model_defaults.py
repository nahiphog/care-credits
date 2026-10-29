"""SDD OPEN-03 provisional DEMO-01 model identity. Never includes API keys or confirmation."""

PROVISIONAL_MODEL = {
    'MODEL_ID': 'nvidia/nemotron-3-super-120b-a12b',
    'MODEL_WEIGHTS_URL': 'https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16',
    'MODEL_LICENSE_URL': 'https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16/blob/main/LICENSE',
    'MODEL_PUBLISHER': 'NVIDIA',
    'MODEL_HOST': 'Nebius Token Factory',
    'MODEL_BASE_URL': 'https://api.tokenfactory.nebius.com/v1',
    'MODEL_MAX_INPUT_CHARS': '12000',
    'MODEL_MAX_OUTPUT_TOKENS': '4000',
}


def apply_provisional_model(settings: dict) -> dict:
    filled = dict(settings)
    for key, default in PROVISIONAL_MODEL.items():
        if not (filled.get(key) or '').strip():
            filled[key] = default
    return filled


def env_or_provisional(name: str, environ: dict | None = None) -> str:
    source = environ if environ is not None else __import__('os').environ
    current = (source.get(name) or '').strip()
    if current:
        return current
    return PROVISIONAL_MODEL.get(name, '')


def using_provisional(name: str, environ: dict | None = None) -> bool:
    """True when the value is the OPEN-03 sample default, not an owner-set env field."""
    source = environ if environ is not None else __import__('os').environ
    return not (source.get(name) or '').strip() and name in PROVISIONAL_MODEL
