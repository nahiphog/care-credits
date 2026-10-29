"""Week-key-first worker, Tavily, and Firehose pipeline tests."""
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scraper import tavily as tavily_mod
from scraper import firehose as firehose_mod
from scraper.worker import run_job, run_weekly_batch, fetch_existing_events
from scraper.week_store import WeekPartitionStore
from shared.contracts import compute_source_key, week_key_for_date


MODEL_ENV = {
    'MODEL_ID': 'test/open-weight-model', 'MODEL_API_KEY': 'test-secret',
    'MODEL_WEIGHTS_URL': 'https://example.org/weights', 'MODEL_LICENSE_URL': 'https://example.org/license',
    'MODEL_OPEN_WEIGHT_CONFIRMED': 'true', 'MODEL_BASE_URL': 'https://example.org/v1',
    'MODEL_MAX_INPUT_CHARS': '12000', 'MODEL_MAX_OUTPUT_TOKENS': '4000',
}

QUOTE = (
    'Primary Care Update organised by Medical School in Kuala Lumpur, Malaysia. '
    'Conference 2026-06-12. Online primary care conference.'
)


def model_candidate(title='Primary Care Update', url='https://example.org/primary-care', start='2026-06-12'):
    return {
        'title': title,
        'provider': 'Medical School',
        'mode': 'online',
        'country': 'MY',
        'start_date': start,
        'source_url': url,
        'source_text': QUOTE,
        'evidence': {key: QUOTE for key in ['title', 'provider', 'mode', 'country', 'start_date']},
        'week_key': week_key_for_date(start),
        'scrape_week_key': week_key_for_date(None),
        'source_key': compute_source_key(url, title, start),
    }


class RunJobEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, MODEL_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.firehose = patch('scraper.worker.firehose_configured', return_value=False)
        self.firehose.start()
        self.addCleanup(self.firehose.stop)

    def test_run_job_adds_week_key_and_candidates_by_week(self):
        sources = [{
            'url': 'https://example.org/primary-care',
            'title': 'Primary Care Update',
            'snippet': QUOTE,
            'raw_content': QUOTE,
            'extraction_status': 'success',
            'verification_status': 'unverified',
        }]
        with patch('scraper.worker.discover', return_value={'sources': sources, 'warnings': [], 'usage': {'tavily_credits': 1}}), patch(
            'scraper.worker.extract_training', return_value=[model_candidate()]
        ):
            result = run_job({'query': 'GP', 'lease_token': 'test', 'id': 'job-1'}, lambda: None)
        self.assertEqual(result['week_key'], week_key_for_date(None))
        self.assertIn('2026-W24', result['candidates_by_week'])
        self.assertEqual(result['candidates_by_week']['2026-W24'][0]['title'], 'Primary Care Update')

    def test_run_job_week_key_respects_job_window(self):
        with patch('scraper.worker.discover', return_value={'sources': [], 'warnings': []}):
            result = run_job({'query': 'GP', 'lease_token': 'test', 'week_key': '2026-W10'}, lambda: None)
        self.assertEqual(result['week_key'], '2026-W10')
        self.assertEqual(result['candidates_by_week'], {})


class RunWeeklyBatchTests(unittest.TestCase):
    def setUp(self):
        self.firehose = patch('scraper.worker.firehose_configured', return_value=False)
        self.firehose.start()
        self.addCleanup(self.firehose.stop)

    def test_no_tavily_when_model_not_configured(self):
        with patch.dict(os.environ, {'MODEL_API_KEY': ''}, clear=False), patch('scraper.worker.discover') as discover:
            result = run_weekly_batch(
                topics=[{'query': 'site:afpm.org.my CME', 'max_results': 5}],
                client=None, week_key='2026-W43', store=WeekPartitionStore(path=None, data={}),
            )
        discover.assert_not_called()
        self.assertEqual(result['status'], 'not_ready')
        self.assertTrue(any('model is ready' in w for w in result['warnings']))

    def test_week_first_dedup_and_push(self):
        store = WeekPartitionStore(path=None, data={})
        sources = [{
            'url': 'https://example.org/primary-care',
            'title': 'Primary Care Update',
            'raw_content': QUOTE,
            'extraction_status': 'success',
            'verification_status': 'unverified',
        }]
        # A near-duplicate already in the catalogue for the dedup path.
        existing = [{
            'source_key': 'known',
            'title': 'Known Duplicate CME',
            'provider': 'Medical School',
            'start_date': '2026-06-12',
        }]
        pushed = {}

        class FakeClient:
            def get(self, path, params=None):
                return SimpleNamespace(status_code=200, json=lambda: existing)

            def post(self, path, json=None):
                pushed['path'] = path
                pushed['body'] = json
                return SimpleNamespace(status_code=200, json=lambda: {'batch_id': 'b1', 'accepted': 1, 'rejected': 0})

        new = model_candidate()
        dup = model_candidate(title='Known Duplicate CME', url='https://example.org/dup')
        with patch.dict(os.environ, MODEL_ENV), patch(
            'scraper.worker.discover', return_value={'sources': sources, 'warnings': [], 'usage': {'tavily_credits': 2}}
        ), patch('scraper.worker.extract_training', return_value=[new, dup]):
            result = run_weekly_batch(
                topics=[{'query': 'site:afpm.org.my CME', 'max_results': 5, 'topic_id': 'afpm-cme'}],
                client=FakeClient(), week_key='2026-W43', store=store, operator_id='scraper-worker',
            )
        # Pushed to the ingestion batch endpoint, week-key first with source_key on every event.
        self.assertEqual(pushed['path'], '/internal/v1/ingestion/batches/push')
        self.assertEqual(pushed['body']['operator_id'], 'scraper-worker')
        self.assertEqual(len(pushed['body']['events']), 1)
        event = pushed['body']['events'][0]
        self.assertEqual(event['week_key'], '2026-W24')
        self.assertTrue(event['source_key'])
        # The near-duplicate was filtered, only the new event is reported.
        self.assertIn('2026-W24', result['candidates_by_week'])
        self.assertEqual(len(result['candidates_by_week']['2026-W24']), 1)
        self.assertEqual(result['accepted'], 1)
        self.assertEqual(result['week_key'], '2026-W43')
        self.assertIn('2026-W43', result['weeks'])

    def test_already_seen_topic_is_skipped(self):
        store = WeekPartitionStore(path=None, data={})
        store.mark_topic_seen('2026-W43', 'site:afpm.org.my CME')
        with patch.dict(os.environ, MODEL_ENV), patch('scraper.worker.discover') as discover:
            run_weekly_batch(
                topics=[{'query': 'site:afpm.org.my CME', 'max_results': 5}],
                client=None, week_key='2026-W43', store=store,
            )
        discover.assert_not_called()

    def test_already_extracted_url_is_not_reprocessed(self):
        store = WeekPartitionStore(path=None, data={})
        store.put_source('2026-W43', {'url': 'https://example.org/primary-care', 'raw_content': QUOTE})
        sources = [{'url': 'https://example.org/primary-care', 'raw_content': QUOTE, 'extraction_status': 'success'}]
        with patch.dict(os.environ, MODEL_ENV), patch(
            'scraper.worker.discover', return_value={'sources': sources, 'warnings': [], 'usage': {}}
        ), patch('scraper.worker.extract_training') as extract:
            run_weekly_batch(
                topics=[{'query': 'site:afpm.org.my CME', 'max_results': 5}],
                client=None, week_key='2026-W43', store=store,
            )
        extract.assert_not_called()


class FetchExistingEventsTests(unittest.TestCase):
    def test_returns_empty_without_client(self):
        self.assertEqual(fetch_existing_events(None, '2026-10-19'), [])

    def test_reads_catalogue_rows(self):
        rows = [{'source_key': 'a', 'title': 'x'}]

        class FakeClient:
            def get(self, path, params=None):
                assert params['from_date'] == '2026-10-19'
                return SimpleNamespace(status_code=200, json=lambda: rows)

        self.assertEqual(fetch_existing_events(FakeClient(), '2026-10-19'), rows)


class TavilyCanonicalizationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TAVILY_API_KEY': 'test-only'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_tracking_params_dedupe_and_week_key_stamped(self):
        replies = [
            {'results': [
                {'url': 'https://example.org/event?utm_source=news', 'title': 'Course', 'content': 'Snippet'},
                {'url': 'https://example.org/event?utm_source=other#frag'},
            ]},
            {'results': [{'url': 'https://example.org/event', 'raw_content': 'Event details'}]},
        ]
        with patch.object(tavily_mod, 'urlopen', side_effect=[io.BytesIO(json.dumps(x).encode()) for x in replies]) as call:
            result = tavily_mod.discover('cardiology', 5)
        extract = call.call_args_list[1].args[0]
        # Both tracking variants collapse to one canonical URL before /extract.
        self.assertEqual(json.loads(extract.data)['urls'], ['https://example.org/event'])
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['week_key'], week_key_for_date(None))
        self.assertEqual(result['sources'][0]['week_key'], week_key_for_date(None))


class FirehoseCacheTests(unittest.TestCase):
    def setUp(self):
        firehose_mod.reset_tap_cache()
        self.addCleanup(firehose_mod.reset_tap_cache)
        self.env = patch.dict(os.environ, {'FIREHOSE_MGMT_KEY': 'fhm_test-only-key'}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_tap_token_cached_per_week(self):
        sse = (
            'event: update\n'
            'data: {"document":{"url":"https://example.org/cme","title":"Malaysia CME course",'
            '"markdown":"CPD course in Kuala Lumpur"}}\n'
            '\n'
        )
        calls = []

        def fake_request(method, path, token, payload=None, query=None, timeout=20):
            calls.append((method, path))
            if path == '/v1/taps':
                return {'taps': [{'name': 'CareCredits CPD', 'token': 'fh_tap-token'}]}
            if path == '/v1/rules':
                return {'rules': [{'tag': 'my-cpd'}, {'tag': 'my-events'}]}
            if path == '/v1/stream':
                return {'sse': sse}
            raise AssertionError(path)

        with patch.object(firehose_mod, 'firehose_request', side_effect=fake_request):
            first = firehose_mod.discover('Malaysia CME course', 5, week_key='2026-W43')
            second = firehose_mod.discover('Malaysia CME course', 5, week_key='2026-W43')
        # ensure_tap + ensure_rules only run once; the second call reuses the cached token.
        self.assertEqual([c for c in calls if c[1] == '/v1/taps'], [('GET', '/v1/taps')])
        self.assertEqual([c for c in calls if c[1] == '/v1/rules'], [('GET', '/v1/rules')])
        self.assertEqual(first['week_key'], '2026-W43')
        self.assertEqual(second['sources'][0]['week_key'], '2026-W43')


if __name__ == '__main__':
    unittest.main()
