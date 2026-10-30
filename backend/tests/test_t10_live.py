"""T-10 live Tavily + open-weight run.

Skips unless T10_LIVE=1 and DEMO-01 keys are confirmed. That gate is required so the
default suite cannot spend credits. Redacted evidence is written under .data/.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / '.data' / 't10-evidence.json'
SECRETS = ('TAVILY_API_KEY', 'MODEL_API_KEY', 'TYPESAFE_API_KEY', 'SCRAPER_SERVICE_TOKEN', 'POSTGRES_PASSWORD', 'GOOGLE_CLIENT_SECRET')


def _redact(value):
    text = json.dumps(value)
    for name in SECRETS:
        secret = (os.getenv(name) or '').strip()
        if secret:
            text = text.replace(secret, '[' + name + ']')
    return json.loads(text)


class LiveT10Tests(unittest.TestCase):
    def test_live_run_requires_explicit_opt_in(self):
        text = Path(__file__).read_text(encoding='utf-8')
        self.assertIn("T10_LIVE", text)
        self.assertIn('live_ready()', text)
        from scripts.demo_readiness import live_ready

        self.assertIsInstance(live_ready(), bool)

    def test_bounded_search_extract_and_model(self):
        from scraper.extraction import ExtractionError, extract_training
        from scraper.tavily import discover
        from shared.model_defaults import env_or_provisional

        if os.getenv('T10_LIVE') != '1':
            self.skipTest('Set T10_LIVE=1 to spend Tavily and model credits for T-10')
        from scripts.demo_readiness import load_owner_env, live_ready
        load_owner_env()
        if not live_ready():
            self.skipTest('Live DEMO-01 remains owner-blocked until MODEL_API_KEY and MODEL_OPEN_WEIGHT_CONFIRMED=true')

        result = discover('GP CME', 1)
        self.assertEqual(result['provider'], 'tavily')
        self.assertLessEqual(len(result['sources']), 1)
        evidence = {
            'query': result['query'],
            'retrieved_at': result['retrieved_at'],
            'source_count': len(result['sources']),
            'warnings': result['warnings'],
            'usage': result['usage'],
            'model_id': env_or_provisional('MODEL_ID'),
            'model_host': env_or_provisional('MODEL_HOST'),
            'model_weights_url': env_or_provisional('MODEL_WEIGHTS_URL'),
            'model_license_url': env_or_provisional('MODEL_LICENSE_URL'),
            'sources': [
                {
                    'url': item['url'],
                    'extraction_status': item['extraction_status'],
                    'has_raw': bool(item.get('raw_content')),
                }
                for item in result['sources']
            ],
            'candidates': [],
            'model_error': None,
        }
        source = result['sources'][0] if result['sources'] else None
        if source and source.get('raw_content'):
            try:
                rows = extract_training(source)
                evidence['candidates'] = [
                    {
                        'title': row.get('title'),
                        'model_id': row.get('model_id'),
                        'evidence_fields': sorted((row.get('evidence') or {}).keys()),
                    }
                    for row in rows
                ]
            except ExtractionError as exc:
                evidence['model_error'] = str(exc)
        payload = _redact(evidence)
        dumped = json.dumps(payload)
        for name in SECRETS:
            secret = (os.getenv(name) or '').strip()
            if secret:
                self.assertNotIn(secret, dumped)
            self.assertNotIn(name + '=', dumped)
        EVIDENCE.parent.mkdir(exist_ok=True)
        EVIDENCE.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        self.assertTrue(payload['model_id'])
        self.assertTrue(payload['model_weights_url'])
        self.assertTrue(payload['model_license_url'])
