"""Scraper liveness/readiness without paid provider calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import uuid

from shared.model_defaults import env_or_provisional
from shared.contracts import week_key_for_date, week_window


DEFAULT_BACKEND_INTERNAL_URL = 'http://127.0.0.1:8000'


def backend_internal_url() -> str:
    """Match scraper/worker.py: unset BACKEND_INTERNAL_URL defaults to local backend."""
    return (os.getenv('BACKEND_INTERNAL_URL') or DEFAULT_BACKEND_INTERNAL_URL).strip() or DEFAULT_BACKEND_INTERNAL_URL


def ready():
    missing = [name for name in ('SCRAPER_SERVICE_TOKEN',) if not (os.getenv(name) or '').strip()]
    model_configured = bool((os.getenv('MODEL_API_KEY') or '').strip())
    missing_model = []
    if model_configured:
        missing_model = [
            name for name in ('MODEL_ID', 'MODEL_MAX_INPUT_CHARS', 'MODEL_MAX_OUTPUT_TOKENS', 'MODEL_WEIGHTS_URL', 'MODEL_LICENSE_URL')
            if not env_or_provisional(name)
        ]
        if os.getenv('MODEL_OPEN_WEIGHT_CONFIRMED') != 'true':
            missing_model.append('MODEL_OPEN_WEIGHT_CONFIRMED')
    week_key = week_key_for_date(None)
    window_start, window_end = week_window(week_key)
    return {
        'status': 'ready' if not missing else 'not_ready',
        'missing': missing,
        'backend_internal_url': backend_internal_url(),
        'tavily_configured': bool((os.getenv('TAVILY_API_KEY') or '').strip()),
        'model_configured': model_configured,
        'model_ready': model_configured and not missing_model,
        'missing_model': missing_model,
        # Week-key-first partition diagnostics (Asia/Kuala_Lumpur).
        'week_key': week_key,
        'week_window': {'start': window_start, 'end': window_end},
        'weekly_batch_mode': (os.getenv('SCRAPER_WEEKLY_BATCH') or '').strip().lower() == 'true',
    }


class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = (self.path.split('?', 1)[0] or '/').rstrip('/') or '/'
        if path == '/health':
            self._send(200, {'status': 'ok'})
            return
        if path == '/health/live':
            self._send(200, {'status': 'live'})
            return
        if path == '/health/ready':
            payload = ready()
            self._send(200 if payload['status'] == 'ready' else 503, payload)
            return
        self._send(
            404,
            {
                'error': {
                    'code': 'not_found',
                    'message': 'Not found.',
                    'request_id': uuid.uuid4().hex,
                }
            },
        )


def start(port=None):
    host = (os.getenv('SCRAPER_HEALTH_HOST') or '127.0.0.1').strip() or '127.0.0.1'
    port = int(port or os.getenv('SCRAPER_HEALTH_PORT') or 8002)
    server = ThreadingHTTPServer((host, port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
