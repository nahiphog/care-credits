"""Run each module's own tests once, in a fresh process with no deployment credentials.

Examples:
    python scripts/test_backend.py
    python scripts/test_backend.py --module backend.tests.test_architecture
    python scripts/test_backend.py --module backend.tests.test_serverless --module scraper.tests.test_week_store
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def modules():
    return sorted(
        '.'.join(path.relative_to(ROOT).with_suffix('').parts)
        for directory in ('backend/tests', 'scraper/tests')
        for path in (ROOT / directory).glob('test_*.py')
    )


def isolated_environment(inherited):
    """Preserve OS/tool paths while replacing all application/provider configuration."""
    prefixes = ('DATABASE', 'POSTGRES', 'PG', 'NEON', 'MODEL_', 'TAVILY_', 'TYPESAFE_',
                'JEV_', 'FIREHOSE_', 'SCRAPER_', 'GOOGLE_', 'SMTP_', 'MAIL_', 'VERCEL_',
                'AWS_', 'AZURE_', 'OPENAI_', 'ANTHROPIC_', 'NEBIUS_', 'T08_', 'T10_')
    suffixes = ('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD')
    settings = {'APP_ENV', 'DEMO_MODE', 'ALLOW_SIGNUP', 'SERVERLESS_MODE', 'CRON_SECRET',
                'BACKEND_URL', 'BACKEND_INTERNAL_URL', 'PUBLIC_API_BASE', 'PUBLIC_FRONTEND_BASE',
                'ALLOWED_ORIGINS', 'CATALOGUE_AUTO_PUBLISH_NEW', 'DIGEST_ENABLED',
                'DAILY_SCRAPE_ENABLED', 'SCRAPE_TOPICS_FILE', 'DAILY_SCRAPE_JOB_CEILING'}
    env = {key: value for key, value in inherited.items()
           if key.upper() not in settings and not key.upper().startswith(prefixes)
           and not key.upper().endswith(suffixes)}
    env.update({
        'PYTHONPATH': str(ROOT) + os.pathsep + str(ROOT / 'backend'),
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
        # Fail safely even if a test accidentally uses the default engine.
        'DATABASE_URL': 'sqlite:///:memory:',
        'APP_ENV': 'test', 'DEMO_MODE': 'false', 'SERVERLESS_MODE': 'false',
        'DAILY_SCRAPE_ENABLED': 'false', 'DIGEST_ENABLED': 'false',
    })
    return env


def run_module(name):
    sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
    module = importlib.import_module(name)
    suite = unittest.TestSuite()
    seen = set()
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls in seen or not issubclass(cls, unittest.TestCase) or cls.__module__ != name:
            continue
        seen.add(cls)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    print('\n' + name, flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', action='append', help='Run only this dotted test module; repeatable.')
    parser.add_argument('--_child', help=argparse.SUPPRESS)
    args = parser.parse_args()
    available = modules()
    selected = [args._child] if args._child else args.module or available
    unknown = set(selected) - set(available)
    if unknown:
        parser.error('Unknown test module(s): ' + ', '.join(sorted(unknown)))
    if args._child:
        safe_env = isolated_environment(os.environ)
        os.environ.clear()
        os.environ.update(safe_env)
        return run_module(args._child)
    failed = []
    for name in selected:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--_child', name],
                                cwd=ROOT, env=isolated_environment(os.environ))
        if result.returncode:
            failed.append(name)
    print(f'\nModules: {len(selected)}; failed: {len(failed)}', flush=True)
    for name in failed:
        print('FAILED: ' + name)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
