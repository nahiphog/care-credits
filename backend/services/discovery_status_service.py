import os
from domain.errors import DomainError
from repository import discovery_repository as repository
from shared.contracts import public_web_url
from shared.model_defaults import env_or_provisional, using_provisional
from services.catalogue_review import auto_publish_new
from jev import api_key as typesafe_key
from oauth import configured as google_oauth
from infrastructure.scraper_client import status as _scraper_service_status
PAID_SCRAPE_BLOCKED = 'Live discovery stays off until Tavily and the open-weight model are ready.'

def _env_int_value(raw):
    try:
        value = int((raw or '').strip())
    except ValueError:
        return None
    return value if value > 0 else None

def _paid_scrape_ready(scraper=None):
    """Auto daily scrape spends Tavily; require the same live gate as /live enqueue."""
    scraper = scraper if scraper is not None else _scraper_service_status()
    return bool(scraper.get('status', 'ready') == 'ready' and scraper.get('tavily_configured') and scraper.get('model_ready'))

def _reject_tavily_spend_without_model():
    """Keep curl/API aligned with UI paid_scrape_ready: fail closed until Tavily+model are ready."""
    if not _paid_scrape_ready():
        raise DomainError(409, PAID_SCRAPE_BLOCKED)

def services(user=None, db=None):
    database = 'ready'
    try:
        repository.check_connection(db)
    except Exception:
        database = 'unavailable'
    scraper = _scraper_service_status()
    return {'backend': 'ready' if database == 'ready' else 'degraded', 'database': database, 'database_owner': 'backend', 'scraper': scraper, 'paid_scrape_ready': _paid_scrape_ready(scraper), 'frontend': 'this portal'}

def integrations(user=None):
    weights = env_or_provisional('MODEL_WEIGHTS_URL') or None
    license_url = env_or_provisional('MODEL_LICENSE_URL') or None
    input_chars = _env_int_value(env_or_provisional('MODEL_MAX_INPUT_CHARS'))
    output_tokens = _env_int_value(env_or_provisional('MODEL_MAX_OUTPUT_TOKENS'))
    return {'model_id': env_or_provisional('MODEL_ID') or None, 'model_publisher': env_or_provisional('MODEL_PUBLISHER') or None, 'model_host': env_or_provisional('MODEL_HOST') or None, 'model_weights_url': public_web_url(weights), 'model_license_url': public_web_url(license_url), 'model_identity_provisional': using_provisional('MODEL_ID'), 'model_publisher_provisional': using_provisional('MODEL_PUBLISHER'), 'model_host_provisional': using_provisional('MODEL_HOST'), 'model_weights_provisional': using_provisional('MODEL_WEIGHTS_URL'), 'model_license_provisional': using_provisional('MODEL_LICENSE_URL'), 'model_open_weight_confirmed': os.getenv('MODEL_OPEN_WEIGHT_CONFIRMED') == 'true', 'model_caps_configured': bool(input_chars and output_tokens), 'model_caps_provisional': using_provisional('MODEL_MAX_INPUT_CHARS') or using_provisional('MODEL_MAX_OUTPUT_TOKENS'), 'model_max_input_chars': input_chars, 'model_max_output_tokens': output_tokens, 'model_key_configured': bool((os.getenv('MODEL_API_KEY') or '').strip() or os.getenv('MODEL_KEY_CONFIGURED') == 'true'), 'typesafe_configured': bool(typesafe_key()), 'scraper_token_configured': bool((os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()), 'google_oauth': google_oauth(), 'catalogue_auto_publish_new': auto_publish_new()}
