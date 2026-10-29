import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scraper import firehose as f
from scraper.worker import merge_sources, public_sources, run_job


SSE = (
    'event: connected\n'
    'data: {}\n'
    '\n'
    'event: update\n'
    'data: {"document":{"url":"https://example.org/cme#one","title":"Malaysia CME course","markdown":"CPD course in Kuala Lumpur"}}\n'
    '\n'
    'event: update\n'
    'data: {"document":{"url":"https://example.org/cme#two","title":"Malaysia CME course","markdown":"same page"}}\n'
    '\n'
    'event: end\n'
    'data: {}\n'
    '\n'
)


class FirehoseTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREHOSE_MGMT_KEY': 'fhm_test-only-key'}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_key_makes_no_call(self):
        with patch.dict(os.environ, {'FIREHOSE_MGMT_KEY': '', 'FIREHOSE_MANAGEMENT_KEY': ''}), patch.object(f, 'urlopen') as call:
            self.assertFalse(f.configured())
            with self.assertRaises(f.FirehoseError) as error:
                f.discover('GP CPD')
            self.assertEqual(error.exception.status_code, 503)
            call.assert_not_called()

    def test_ensure_tap_reuse_and_stream_dedupe(self):
        replies = [
            {'taps': [{'name': 'CareCredits CPD', 'token': 'fh_tap-token'}]},
            {'rules': [{'tag': 'my-cpd'}, {'tag': 'my-events'}]},
            {'sse': SSE},
        ]

        def fake_request(method, path, token, payload=None, query=None, timeout=20):
            self.assertTrue(token.startswith('fhm_') or token.startswith('fh_'))
            if path == '/v1/taps' and method == 'GET':
                return replies[0]
            if path == '/v1/rules' and method == 'GET':
                return replies[1]
            if path == '/v1/stream':
                self.assertEqual(query['since'], '24h')
                return replies[2]
            raise AssertionError(path)

        with patch.object(f, 'firehose_request', side_effect=fake_request):
            result = f.discover('Malaysia CME course', 5)
        self.assertEqual(result['provider'], 'firehose')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['url'], 'https://example.org/cme')
        self.assertEqual(result['sources'][0]['extraction_status'], 'success')
        self.assertEqual(result['sources'][0]['retrieved_at'], result['retrieved_at'])
        self.assertTrue(result['retrieved_at'])
        self.assertNotIn('fhm_test-only-key', json.dumps(result))

    def test_whitespace_only_document_is_extraction_failed(self):
        """Parity with Tavily: whitespace-only pages must not claim extraction_status success."""
        events = [
            (
                'update',
                {
                    'document': {
                        'url': 'https://example.org/blank',
                        'title': 'Blank CME page',
                        'diff': {'chunks': [{'typ': 'ins', 'text': '   \n\t  '}]},
                    }
                },
            )
        ]
        sources = f.sources_from_events(events, 'Blank CME page', 5)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['extraction_status'], 'failed')
        self.assertIsNone(sources[0]['raw_content'])
        self.assertEqual(sources[0]['snippet'], '')

    def test_upstream_errors_sanitized(self):
        error = HTTPError('https://api.firehose.com/v1/taps', 401, 'secret-provider-body', {}, None)
        with patch.object(f, 'urlopen', side_effect=error):
            with self.assertRaises(f.FirehoseError) as caught:
                f.firehose_request('GET', '/v1/taps', 'fhm_test-only-key')
            self.assertEqual(caught.exception.status_code, 503)
            self.assertNotIn('secret', caught.exception.detail)

    def test_ensure_tap_empty_create_without_token_is_firehose_error(self):
        """Offline soft-fail path: empty tap list + tokenless create must not IndexError."""
        gets = {'n': 0}

        def fake_request(method, path, token, payload=None, query=None, timeout=20):
            if path == '/v1/taps' and method == 'GET':
                gets['n'] += 1
                return {'taps': []}
            if path == '/v1/taps' and method == 'POST':
                return {'name': 'CareCredits CPD'}  # no token
            raise AssertionError(path)

        with patch.object(f, 'firehose_request', side_effect=fake_request):
            with self.assertRaises(f.FirehoseError) as caught:
                f.ensure_tap('fhm_test-only-key')
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn('CareCredits CPD tap', caught.exception.detail)
        self.assertGreaterEqual(gets['n'], 2)

    def test_ensure_tap_does_not_use_unrelated_tap(self):
        """Create miss must not silently stream from another account tap."""

        def fake_request(method, path, token, payload=None, query=None, timeout=20):
            if path == '/v1/taps' and method == 'GET':
                return {'taps': [{'name': 'Other product', 'token': 'fh_other'}]}
            if path == '/v1/taps' and method == 'POST':
                raise f.FirehoseError(422, 'Firehose rejected the request.')
            raise AssertionError(path)

        with patch.object(f, 'firehose_request', side_effect=fake_request):
            with self.assertRaises(f.FirehoseError) as caught:
                f.ensure_tap('fhm_test-only-key')
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn('CareCredits CPD tap', caught.exception.detail)

    def test_worker_soft_fails_firehose_and_keeps_tavily_sources(self):
        from scraper.firehose import FirehoseError

        tavily = {
            'sources': [{
                'url': 'https://example.org/tavily',
                'title': 'Tavily',
                'snippet': 'Snippet',
                'raw_content': 'Page text',
                'extraction_status': 'success',
                'verification_status': 'unverified',
            }],
            'warnings': [],
            'usage': {'tavily_credits': 1},
        }
        with patch('scraper.worker.discover', return_value=tavily), patch(
            'scraper.worker.firehose_configured', return_value=True
        ), patch(
            'scraper.worker.firehose_discover',
            side_effect=FirehoseError(504, 'Firehose is unavailable or timed out.'),
        ), patch('scraper.worker.configuration', return_value='https://example.org/v1'), patch(
            'scraper.worker.extract_training', return_value=[]
        ), patch('scraper.worker.heuristic_extract', return_value=[]):
            result = run_job({'query': 'GP', 'lease_token': 'test', 'max_results': 5}, lambda: None)
        self.assertEqual([item['url'] for item in result['sources']], ['https://example.org/tavily'])
        self.assertTrue(any('Firehose' in warning for warning in result['warnings']))
        self.assertEqual(result['usage']['tavily_credits'], 1)
        # Soft Firehose fill failure must not alone mark a clean Tavily extract as partial.
        self.assertEqual(result['status'], 'succeeded')

    def test_worker_merges_firehose_when_configured(self):
        tavily = {
            'sources': [{
                'url': 'https://example.org/tavily',
                'title': 'Tavily',
                'snippet': 'Snippet',
                'raw_content': 'Page text',
                'extraction_status': 'success',
                'verification_status': 'unverified',
            }],
            'warnings': [],
        }
        extra = {
            'sources': [{
                'url': 'https://example.org/firehose',
                'title': 'Firehose CME',
                'snippet': 'Malaysia CME',
                'raw_content': 'Malaysia CME course',
                'extraction_status': 'success',
                'verification_status': 'unverified',
            }],
            'warnings': [],
        }
        with patch('scraper.worker.discover', return_value=tavily), patch('scraper.worker.firehose_configured', return_value=True), patch('scraper.worker.firehose_discover', return_value=extra) as firehose, patch('scraper.worker.configuration', return_value='https://example.org/v1'), patch('scraper.worker.extract_training', return_value=[]), patch('scraper.worker.heuristic_extract', return_value=[]):
            result = run_job({'query': 'GP', 'lease_token': 'test'}, lambda: None)
        urls = [item['url'] for item in result['sources']]
        self.assertIn('https://example.org/tavily', urls)
        self.assertIn('https://example.org/firehose', urls)
        firehose.assert_called_once_with('GP', 4)

    def test_worker_skips_firehose_when_tavily_filled_the_job_limit(self):
        for limit in (3, 5):
            with self.subTest(limit=limit):
                tavily = {
                    'sources': [
                        {
                            'url': f'https://example.org/tavily-{i}',
                            'title': 'Tavily',
                            'snippet': 'Snippet',
                            'raw_content': 'Page text',
                            'extraction_status': 'success',
                            'verification_status': 'unverified',
                        }
                        for i in range(limit)
                    ],
                    'warnings': [],
                }
                with patch('scraper.worker.discover', return_value=tavily), patch(
                    'scraper.worker.firehose_configured', return_value=True
                ), patch('scraper.worker.firehose_discover') as firehose, patch(
                    'scraper.worker.configuration', return_value='https://example.org/v1'
                ), patch('scraper.worker.extract_training', return_value=[]), patch(
                    'scraper.worker.heuristic_extract', return_value=[]
                ):
                    result = run_job({'query': 'GP', 'lease_token': 'test', 'max_results': limit}, lambda: None)
                firehose.assert_not_called()
                self.assertEqual(len(result['sources']), limit)

    def test_worker_asks_firehose_only_for_remaining_slots(self):
        tavily = {
            'sources': [
                {
                    'url': 'https://example.org/tavily-0',
                    'title': 'Tavily',
                    'snippet': 'Snippet',
                    'raw_content': 'Page text',
                    'extraction_status': 'success',
                    'verification_status': 'unverified',
                },
                {
                    'url': 'https://example.org/tavily-1',
                    'title': 'Tavily',
                    'snippet': 'Snippet',
                    'raw_content': 'Page text',
                    'extraction_status': 'success',
                    'verification_status': 'unverified',
                },
            ],
            'warnings': [],
            'usage': {'tavily_credits': 2},
        }
        extra = {
            'sources': [
                {
                    'url': f'https://example.org/firehose-{i}',
                    'title': 'Firehose CME',
                    'snippet': 'Malaysia CME',
                    'raw_content': 'Malaysia CME course',
                    'extraction_status': 'success',
                    'verification_status': 'unverified',
                }
                for i in range(5)
            ],
            'warnings': [],
        }
        with patch('scraper.worker.discover', return_value=tavily), patch(
            'scraper.worker.firehose_configured', return_value=True
        ), patch('scraper.worker.firehose_discover', return_value=extra) as firehose, patch(
            'scraper.worker.configuration', return_value='https://example.org/v1'
        ), patch('scraper.worker.extract_training', return_value=[]), patch(
            'scraper.worker.heuristic_extract', return_value=[]
        ):
            result = run_job({'query': 'GP', 'lease_token': 'test', 'max_results': 4}, lambda: None)
        firehose.assert_called_once_with('GP', 2)
        self.assertEqual(len(result['sources']), 4)
        self.assertEqual(result['usage']['tavily_credits'], 2)
        self.assertIsNone(result['usage']['model_tokens'])

    def test_merge_sources_dedupes(self):
        merged = merge_sources(
            [{'url': 'https://example.org/a'}],
            [{'url': 'https://example.org/a'}, {'url': 'https://example.org/b'}],
            limit=5,
        )
        self.assertEqual([item['url'] for item in merged], ['https://example.org/a', 'https://example.org/b'])

    def test_merge_sources_stays_within_job_limit(self):
        extra = [{'url': f'https://example.org/{i}'} for i in range(8)]
        merged = merge_sources([{'url': 'https://example.org/seed'}], extra, limit=5)
        self.assertEqual(len(merged), 5)

    def test_merge_sources_skips_non_dict_rows(self):
        # Junk Firehose/Tavily rows must not crash fill (parity with public_sources).
        merged = merge_sources(
            ['bad', {'url': 'https://example.org/a'}],
            [None, 'x', {'url': 'https://example.org/b'}],
            limit=5,
        )
        self.assertEqual([item['url'] for item in merged], ['https://example.org/a', 'https://example.org/b'])

    def test_public_sources_omit_unsafe_urls(self):
        items = public_sources([
            {'url': 'javascript:alert(1)', 'title': 'Unsafe', 'snippet': 'skip'},
            {'url': 'https://example.org/afpm', 'title': 'Primary Care Update', 'snippet': 'CPD'},
        ])
        self.assertIsNone(items[0]['url'])
        self.assertEqual(items[0]['title'], 'Unsafe')
        self.assertEqual(items[1]['url'], 'https://example.org/afpm')

    def test_public_sources_skips_non_dict_rows(self):
        # Provenance residual: junk list entries must not crash job-complete public_sources.
        items = public_sources([
            'not-a-source',
            None,
            {'url': 'https://example.org/ok', 'title': 'OK', 'snippet': 'CPD', 'retrieved_at': '2026-10-03T00:00:00+00:00'},
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['url'], 'https://example.org/ok')
        self.assertEqual(items[0]['retrieved_at'], '2026-10-03T00:00:00+00:00')

    def test_worker_stamps_provider_retrieved_at_onto_sources(self):
        from scraper.worker import stamp_retrieved_at

        sources = [{'url': 'https://example.org/a', 'title': 'A'}]
        stamped = stamp_retrieved_at(sources, '2026-10-03T05:00:00+00:00')
        self.assertEqual(stamped[0]['retrieved_at'], '2026-10-03T05:00:00+00:00')
        # Existing per-source stamps win over the provider-level value.
        kept = stamp_retrieved_at(
            [{'url': 'https://example.org/b', 'retrieved_at': '2026-10-01T00:00:00+00:00'}],
            '2026-10-03T05:00:00+00:00',
        )
        self.assertEqual(kept[0]['retrieved_at'], '2026-10-01T00:00:00+00:00')

    def test_worker_propagates_tavily_and_firehose_retrieved_at(self):
        tavily = {
            'sources': [{
                'url': 'https://example.org/tavily',
                'title': 'Tavily',
                'snippet': 'Snippet',
                'raw_content': 'Page text',
                'extraction_status': 'success',
                'verification_status': 'unverified',
            }],
            'warnings': [],
            'retrieved_at': '2026-10-03T06:00:00+00:00',
            'usage': {'tavily_credits': 1},
        }
        extra = {
            'sources': [{
                'url': 'https://example.org/firehose',
                'title': 'Firehose CME',
                'snippet': 'Malaysia CME',
                'raw_content': 'Malaysia CME course',
                'extraction_status': 'success',
                'verification_status': 'unverified',
            }],
            'warnings': [],
            'retrieved_at': '2026-10-03T06:05:00+00:00',
        }
        with patch('scraper.worker.discover', return_value=tavily), patch(
            'scraper.worker.firehose_configured', return_value=True
        ), patch('scraper.worker.firehose_discover', return_value=extra), patch(
            'scraper.worker.configuration', return_value='https://example.org/v1'
        ), patch('scraper.worker.extract_training', return_value=[]), patch(
            'scraper.worker.heuristic_extract', return_value=[]
        ):
            result = run_job({'query': 'GP', 'lease_token': 'test', 'max_results': 5}, lambda: None)
        by_url = {item['url']: item['retrieved_at'] for item in result['sources']}
        self.assertEqual(by_url['https://example.org/tavily'], '2026-10-03T06:00:00+00:00')
        self.assertEqual(by_url['https://example.org/firehose'], '2026-10-03T06:05:00+00:00')


if __name__ == '__main__':
    unittest.main()
