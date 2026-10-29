"""Run the three local services, optionally with explicit fictional fixtures."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from dotenv import dotenv_values

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from shared.model_defaults import apply_provisional_model  # noqa: E402


def reserve_local_ports(*preferreds):
    """Bind distinct free ports near each preferred value and keep the sockets until released.

    Sequential free_port() bind-and-close races can hand the same port to backend and scraper
    health when preferred ranges overlap (e.g. both near 8000). Hold sockets until the caller
    is ready to start child processes.
    """
    held = []
    chosen = []
    try:
        for preferred in preferreds:
            preferred = int(preferred)
            for port in (preferred, *range(preferred + 1, preferred + 20)):
                if port in chosen:
                    continue
                sock = socket.socket()
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(('127.0.0.1', port))
                except OSError:
                    sock.close()
                    continue
                held.append(sock)
                chosen.append(sock.getsockname()[1])
                break
            else:
                raise RuntimeError('No free local port near ' + str(preferred))
        return chosen, held
    except Exception:
        for sock in held:
            sock.close()
        raise


def free_port(preferred):
    ports, held = reserve_local_ports(preferred)
    for sock in held:
        sock.close()
    return ports[0]


def is_live_body(payload):
    return isinstance(payload, dict) and payload.get('status') == 'live'


def probe_live(url, timeout=2):
    try:
        with urlopen(url, timeout=timeout) as response:
            if getattr(response, 'status', 200) != 200:
                return False
            payload = json.loads(response.read() or b'{}')
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        return False
    return is_live_body(payload)


def wait_for_live(urls, timeout=60, sleep=0.4):
    pending = dict(urls)
    ready = []
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        for name, url in list(pending.items()):
            if probe_live(url):
                ready.append(name)
                pending.pop(name)
        if pending:
            time.sleep(sleep)
    return ready, list(pending)


MODEL_IDENTITY = (
    'MODEL_ID',
    'MODEL_PUBLISHER',
    'MODEL_HOST',
    'MODEL_WEIGHTS_URL',
    'MODEL_LICENSE_URL',
    'MODEL_OPEN_WEIGHT_CONFIRMED',
    'MODEL_MAX_INPUT_CHARS',
    'MODEL_MAX_OUTPUT_TOKENS',
)
BACKEND_OPTIONAL = (
    'TYPESAFE_API_KEY',
    'JEV_CONFIDENCE_FLOOR',
    'DAILY_SCRAPE_JOB_CEILING',
    'SCRAPE_TOPICS_FILE',
    'GOOGLE_CLIENT_ID',
    'GOOGLE_CLIENT_SECRET',
    'GOOGLE_REDIRECT_URI',
    'CATALOGUE_AUTO_PUBLISH_NEW',
    'MAIL_PROVIDER',
    'DIGEST_ENABLED',
    'DIGEST_LOG_DIR',
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_USER',
    'SMTP_PASSWORD',
    'SMTP_FROM',
)

# Keep local Next instances (3000–3040) mutating the API without a wildcard origin.
# Must stay aligned with backend.main.DEFAULT_ALLOWED_ORIGINS and .env.sample.
LOCAL_DEV_ALLOWED_ORIGINS = (
    'http://localhost:3000,http://127.0.0.1:3000,'
    'http://localhost:3010,http://127.0.0.1:3010,'
    'http://localhost:3020,http://127.0.0.1:3020,'
    'http://localhost:3021,http://127.0.0.1:3021,'
    'http://localhost:3030,http://127.0.0.1:3030,'
    'http://localhost:3040,http://127.0.0.1:3040'
)


def allowed_origins_for_frontend(frontend_port: int) -> str:
    """Union the documented localhost defaults with the selected frontend port."""
    selected = (
        'http://localhost:' + str(frontend_port),
        'http://127.0.0.1:' + str(frontend_port),
    )
    merged = []
    seen = set()
    for origin in LOCAL_DEV_ALLOWED_ORIGINS.split(',') + list(selected):
        origin = origin.strip()
        if not origin or origin in seen:
            continue
        seen.add(origin)
        merged.append(origin)
    return ','.join(merged)


def service_environments(
    root: Path,
    settings: dict,
    environ: dict,
    backend_port: int,
    frontend_port: int,
    health_port: int,
    demo: bool,
    token: str,
    typesafe_keyfile: Path | None = None,
    owner_settings: dict | None = None,
):
    """Split local env so paid secrets stay on the owning process (SEC-01 / DEMO-01).

    OPEN-03 sample identity must not be written into the backend process env: leave those
    fields unset so `/admin/integrations` can label them `*_provisional`. The scraper may
    still receive filled provisional values for local adapter convenience.
    """
    frontend = 'http://127.0.0.1:' + str(frontend_port)
    api = 'http://127.0.0.1:' + str(backend_port)
    health = 'http://127.0.0.1:' + str(health_port)
    common = {**environ, 'NEXT_TELEMETRY_DISABLED': '1', 'PYTHONPATH': str(root) + os.pathsep + str(root / 'backend')}
    for key in list(common):
        if key.startswith(('MODEL_', 'TAVILY_', 'TYPESAFE_', 'JEV_', 'DAILY_', 'SCRAPE_', 'FIREHOSE_', 'GOOGLE_')) or key in (
            'DATABASE_URL',
            'POSTGRES_PASSWORD',
            'SCRAPER_SERVICE_TOKEN',
            'MODEL_API_KEY',
            'SMTP_PASSWORD',
        ):
            common.pop(key)
    db_url = environ.get('DATABASE_URL') or settings.get('DATABASE_URL') or 'sqlite:///' + str(root / '.data' / ('demo.db' if demo else 'carecredits.db'))
    backend = {
        **common,
        'DATABASE_URL': db_url,
        'APP_ENV': 'development',
        'DEMO_MODE': str(demo).lower(),
        'ALLOW_SIGNUP': 'true' if demo else settings.get('ALLOW_SIGNUP', 'false'),
        'SCRAPER_SERVICE_TOKEN': token,
        'DAILY_SCRAPE_ENABLED': 'false' if demo else settings.get('DAILY_SCRAPE_ENABLED', 'true'),
        'PUBLIC_API_BASE': api,
        'PUBLIC_FRONTEND_BASE': frontend,
        'ALLOWED_ORIGINS': allowed_origins_for_frontend(frontend_port),
        'SCRAPER_HEALTH_URL': health,
    }
    owned = owner_settings if owner_settings is not None else settings
    for key in BACKEND_OPTIONAL:
        if settings.get(key):
            backend[key] = settings[key]
    for key in MODEL_IDENTITY:
        if (owned.get(key) or '').strip():
            backend[key] = owned[key]
    if (settings.get('MODEL_API_KEY') or '').strip():
        backend['MODEL_KEY_CONFIGURED'] = 'true'
    if not (backend.get('TYPESAFE_API_KEY') or '').strip():
        keyfile = typesafe_keyfile if typesafe_keyfile is not None else Path.home() / '.typesafe' / 'key'
        try:
            if keyfile.is_file():
                file_key = keyfile.read_text().strip()
                if file_key:
                    backend['TYPESAFE_API_KEY'] = file_key
        except OSError:
            pass
    scraper = {
        **common,
        **{k: v for k, v in settings.items() if k.startswith(('MODEL_', 'TAVILY_', 'FIREHOSE_'))},
        'SCRAPER_SERVICE_TOKEN': token,
        'BACKEND_INTERNAL_URL': api,
        'SCRAPER_HEALTH_HOST': settings.get('SCRAPER_HEALTH_HOST') or '127.0.0.1',
        'SCRAPER_HEALTH_PORT': str(health_port),
    }
    frontend_env = {
        **common,
        'BACKEND_URL': api,
        'NEXT_DIST_DIR': '.data/next-dev-' + str(frontend_port),
        # Prefer polling over native FSEvents when the machine hits EMFILE watch limits
        # (common with multiple Next/Turbopack instances). Does not change production builds.
        'WATCHPACK_POLLING': 'true',
        'CHOKIDAR_USEPOLLING': 'true',
    }
    return backend, scraper, frontend_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--backend-port', type=int, default=int(os.getenv('BACKEND_PORT') or 8000))
    parser.add_argument('--frontend-port', type=int, default=int(os.getenv('FRONTEND_PORT') or 3000))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    owner = {k: v for k, v in dotenv_values(root / '.env').items() if v is not None}
    settings = dict(owner)
    health_preferred = int(settings.get('SCRAPER_HEALTH_PORT') or os.getenv('SCRAPER_HEALTH_PORT') or 8002)
    ports, held_ports = reserve_local_ports(args.backend_port, args.frontend_port, health_preferred)
    backend_port, frontend_port, health_port = ports
    # Release held binds so child processes can listen; ports stay distinct from each other.
    for sock in held_ports:
        sock.close()
    token = settings.get('SCRAPER_SERVICE_TOKEN') or secrets.token_urlsafe(32)
    (root / '.data').mkdir(exist_ok=True)
    backend, scraper, frontend_env = service_environments(
        root,
        settings,
        dict(os.environ),
        backend_port,
        frontend_port,
        health_port,
        args.demo,
        token,
        owner_settings=owner,
    )
    processes = []
    try:
        for command, env, cwd in [
            ([sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', str(backend_port)], backend, root),
            ([sys.executable, '-m', 'scraper.worker'], scraper, root),
            (['npm.cmd' if os.name == 'nt' else 'npm', 'run', 'dev:demo', '--', '--hostname', '127.0.0.1', '--port', str(frontend_port)], frontend_env, root),
        ]:
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True))
        live_urls = {
            'backend': backend['PUBLIC_API_BASE'] + '/health/live',
            'scraper': backend['SCRAPER_HEALTH_URL'] + '/health/live',
            'frontend': backend['PUBLIC_FRONTEND_BASE'] + '/health/live',
        }
        ready, missing = wait_for_live(live_urls)
        if missing:
            print(
                'CareCredits started, but /health/live is not ready for: '
                + ', '.join(missing)
                + '. Frontend '
                + backend['PUBLIC_FRONTEND_BASE']
                + ' — API '
                + backend['PUBLIC_API_BASE'],
                flush=True,
            )
        else:
            print(
                'CareCredits live: '
                + backend['PUBLIC_FRONTEND_BASE']
                + ' — API '
                + backend['PUBLIC_API_BASE']
                + ' — scraper '
                + backend['SCRAPER_HEALTH_URL']
                + ' — Ctrl+C stops all three services.',
                flush=True,
            )
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate() if os.name == 'nt' else os.killpg(p.pid, signal.SIGTERM)
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill() if os.name == 'nt' else os.killpg(p.pid, signal.SIGKILL)


if __name__ == '__main__':
    main()
