"""Tests for the week-key-first partition and deduplication store."""
import os
import tempfile
import unittest

from scraper.week_store import (
    WeekPartitionStore,
    query_unique_key,
    url_unique_key,
    is_near_duplicate,
)
from shared.contracts import compute_source_key, week_key_for_date


def candidate(title='AFPM Primary Care Symposium 2026', provider='Academy of Family Physicians Malaysia',
              start_date='2026-11-14', url='https://afpm.org.my/cme-2026'):
    return {
        'title': title,
        'provider': provider,
        'start_date': start_date,
        'mode': 'in_person',
        'city': 'Kuala Lumpur',
        'country': 'MY',
        'source_url': url,
        'week_key': week_key_for_date(start_date),
        'scrape_week_key': '2026-W43',
        'source_key': compute_source_key(url, title, start_date),
        'evidence': {'title': title},
    }


class UniqueKeyTests(unittest.TestCase):
    def test_query_key_is_week_first_and_normalized(self):
        a = query_unique_key('2026-W43', '  Site:AFPM.org.my   CME  ')
        b = query_unique_key('2026-W43', 'site:afpm.org.my cme')
        self.assertTrue(a.startswith('2026-W43:query:'))
        self.assertEqual(a, b)

    def test_url_key_canonicalizes_before_hashing(self):
        a = url_unique_key('2026-W43', 'https://example.org/event#one?utm_source=x')
        b = url_unique_key('2026-W43', 'https://example.org/event#two')
        self.assertTrue(a.startswith('2026-W43:url:'))
        self.assertEqual(a, b)


class NearDuplicateTests(unittest.TestCase):
    def test_exact_source_key_short_circuit(self):
        cand = candidate()
        existing = [{'source_key': cand['source_key'], 'title': 'different'}]
        match = is_near_duplicate(cand, existing)
        self.assertIsNotNone(match)
        self.assertEqual(match['reason'], 'exact_source_key')

    def test_fingerprint_similarity(self):
        cand = candidate()
        existing = [{
            'source_key': 'other',
            'title': 'AFPM Primary Care Symposium 2026!',
            'provider': 'Academy of Family Physicians Malaysia',
            'start_date': '2026-11-14',
        }]
        match = is_near_duplicate(cand, existing)
        self.assertIsNotNone(match)
        self.assertEqual(match['reason'], 'near_duplicate_fingerprint')

    def test_different_date_is_not_duplicate(self):
        cand = candidate()
        existing = [{
            'source_key': 'other',
            'title': 'AFPM Primary Care Symposium 2026',
            'provider': 'Academy of Family Physicians Malaysia',
            'start_date': '2027-01-01',
        }]
        self.assertIsNone(is_near_duplicate(cand, existing))

    def test_unrelated_title_is_not_duplicate(self):
        cand = candidate()
        existing = [{'source_key': 'o', 'title': 'Totally unrelated webinar', 'provider': 'Someone else'}]
        self.assertIsNone(is_near_duplicate(cand, existing))


class WeekPartitionStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = WeekPartitionStore(path=None, data={})

    def test_outer_key_is_always_week_key_first(self):
        self.store.put_candidate('2026-W43', candidate())
        self.assertEqual(list(self.store.data.keys()), ['2026-W43'])
        bucket = self.store.data['2026-W43']
        self.assertEqual(bucket['week_key'], '2026-W43')
        # Inside the scrape week, events are bucketed again by their own event week first.
        self.assertIn('2026-W46', bucket['events_by_week'])

    def test_topic_and_url_dedup(self):
        self.assertFalse(self.store.topic_seen('2026-W43', 'site:afpm.org.my CME'))
        self.store.mark_topic_seen('2026-W43', 'site:afpm.org.my CME', source_urls=['https://afpm.org.my/cme'])
        self.assertTrue(self.store.topic_seen('2026-W43', 'site:afpm.org.my   cme'))

        source = {'url': 'https://afpm.org.my/cme-2026#x', 'raw_content': 'text'}
        self.assertFalse(self.store.url_seen('2026-W43', source['url']))
        self.store.put_source('2026-W43', source)
        self.assertTrue(self.store.url_seen('2026-W43', 'https://afpm.org.my/cme-2026'))
        cached = self.store.get_cached_source('2026-W43', 'https://afpm.org.my/cme-2026#other')
        self.assertIsNotNone(cached)
        self.assertEqual(cached['url'], 'https://afpm.org.my/cme-2026')

    def test_put_candidate_dedupes_by_source_key(self):
        self.store.put_candidate('2026-W43', candidate())
        self.store.put_candidate('2026-W43', candidate())  # same identity
        self.assertEqual(len(self.store.events_for_week('2026-W43')), 1)

    def test_candidates_by_week_and_export_payload(self):
        self.store.put_candidate('2026-W43', candidate())
        self.store.put_candidate('2026-W43', candidate(
            title='Johor GP Workshop', url='https://moh.gov.my/johor', start_date='2026-12-05'))
        grouped = self.store.candidates_by_week('2026-W43')
        self.assertEqual(sorted(grouped), ['2026-W46', '2026-W49'])

        payload = self.store.export_batch_payload('2026-W43', operator_id='scraper-worker')
        self.assertEqual(payload['operator_id'], 'scraper-worker')
        self.assertEqual(len(payload['events']), 2)
        for event in payload['events']:
            self.assertIn('week_key', event)
            self.assertTrue(event['source_key'])

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'weeks.json')
            store = WeekPartitionStore(path=path, data={})
            store.put_candidate('2026-W43', candidate())
            store.mark_topic_seen('2026-W43', 'site:afpm.org.my CME')
            store.persist()

            reloaded = WeekPartitionStore(path=path)
            self.assertEqual(len(reloaded.events_for_week('2026-W43')), 1)
            self.assertTrue(reloaded.topic_seen('2026-W43', 'site:afpm.org.my CME'))

    def test_env_state_path_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'env-weeks.json')
            os.environ['SCRAPER_STATE_PATH'] = path
            try:
                store = WeekPartitionStore()
                store.put_candidate('2026-W43', candidate())
                store.persist()
                self.assertTrue(os.path.exists(path))
            finally:
                del os.environ['SCRAPER_STATE_PATH']


if __name__ == '__main__':
    unittest.main()
