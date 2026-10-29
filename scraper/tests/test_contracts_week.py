"""Week-key-first data contract tests for shared/contracts.py."""
import hashlib
import unittest
from datetime import date

from shared.contracts import (
    Training,
    validate_evidence,
    canonical_web_url,
    compute_source_key,
    week_key_for_date,
    week_window,
    ensure_week_key_first,
)


class WeekKeyHelpersTests(unittest.TestCase):
    def test_week_key_for_known_date(self):
        self.assertEqual(week_key_for_date('2026-10-25'), '2026-W43')
        self.assertEqual(week_key_for_date(date(2026, 10, 25)), '2026-W43')
        # Monday of the same ISO week resolves to the same key.
        self.assertEqual(week_key_for_date('2026-10-19'), '2026-W43')

    def test_week_key_falls_back_to_scrape_window(self):
        self.assertEqual(week_key_for_date(None, fallback_today=date(2026, 10, 25)), '2026-W43')
        self.assertEqual(week_key_for_date('', fallback_today='2026-10-25'), '2026-W43')
        self.assertEqual(week_key_for_date('not-a-date', fallback_today=date(2026, 10, 25)), '2026-W43')

    def test_week_window_monday_sunday(self):
        self.assertEqual(week_window('2026-W43'), ('2026-10-19', '2026-10-25'))
        self.assertEqual(week_window('2026-W01')[0], week_window('2026-W01')[0])
        with self.assertRaises(ValueError):
            week_window('2026-W54')
        with self.assertRaises(ValueError):
            week_window('not-a-week')

    def test_ensure_week_key_first(self):
        mapping = {}
        bucket = ensure_week_key_first(mapping, '2026-W43')
        self.assertIn('2026-W43', mapping)
        self.assertEqual(bucket['week_key'], '2026-W43')
        self.assertEqual(bucket['window_start'], '2026-10-19')
        self.assertEqual(bucket['window_end'], '2026-10-25')
        # Idempotent: the outer key stays first and is not duplicated.
        again = ensure_week_key_first(mapping, '2026-W43')
        self.assertIs(again, bucket)


class CanonicalUrlTests(unittest.TestCase):
    def test_strips_tracking_and_fragment(self):
        self.assertEqual(
            canonical_web_url('https://Example.org/Event/?utm_source=x&utm_medium=y&id=5#frag'),
            'https://example.org/Event?id=5',
        )
        self.assertEqual(
            canonical_web_url('https://example.org/a#one'),
            canonical_web_url('https://example.org/a#two'),
        )
        self.assertEqual(
            canonical_web_url('https://example.org/a?fbclid=abc&gclid=def'),
            'https://example.org/a',
        )

    def test_rejects_unsafe_urls(self):
        for bad in ('javascript:alert(1)', 'http://localhost/a', 'https://x.local/a',
                    'http://127.0.0.1/a', 'https://user:pass@example.org/a', 'http://[::1]/',
                    'https://example.org:8080/a', None, 123):
            self.assertIsNone(canonical_web_url(bad), bad)


class SourceKeyTests(unittest.TestCase):
    def test_matches_backend_digest_formula(self):
        key = compute_source_key('https://a.org/x#frag', 'Foo Bar', '2026-11-14')
        expected = hashlib.sha256('https://a.org/x|foo bar|2026-11-14'.encode('utf-8')).hexdigest()
        self.assertEqual(key, expected)

    def test_none_start_date_stringifies(self):
        key = compute_source_key('https://a.org/x', 'Title', None)
        expected = hashlib.sha256('https://a.org/x|title|None'.encode('utf-8')).hexdigest()
        self.assertEqual(key, expected)

    def test_date_object_matches_iso_string(self):
        self.assertEqual(
            compute_source_key('https://a.org/x', 'T', date(2026, 11, 14)),
            compute_source_key('https://a.org/x', 'T', '2026-11-14'),
        )


class TrainingWeekFieldsTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            'title': 'Primary Care Update',
            'provider': 'Medical School',
            'mode': 'online',
            'country': 'MY',
            'source_url': 'https://example.org/event',
            'source_text': 'x',
            'evidence': {},
        }
        row.update(overrides)
        return row

    def test_event_week_from_start_date(self):
        t = Training(**self._row(start_date='2026-11-14'))
        self.assertEqual(t.week_key, '2026-W46')
        self.assertTrue(t.scrape_week_key.startswith('20'))
        self.assertEqual(len(t.source_key), 64)
        self.assertEqual(t.source_key, compute_source_key('https://example.org/event', 'Primary Care Update', date(2026, 11, 14)))

    def test_unknown_date_uses_scrape_week(self):
        t = Training(**self._row())
        self.assertEqual(t.week_key, t.scrape_week_key)

    def test_explicit_scrape_week_key_is_honored(self):
        t = Training(**self._row(scrape_week_key='2026-W43'))
        self.assertEqual(t.scrape_week_key, '2026-W43')
        self.assertEqual(t.week_key, '2026-W43')


class EvidenceWhitespaceTests(unittest.TestCase):
    def _training(self, source_text, evidence):
        return Training(
            title='Primary Care Update',
            provider='Medical School',
            mode='online',
            country='MY',
            source_url='https://example.org/event',
            source_text=source_text,
            evidence=evidence,
        )

    def test_collapsed_whitespace_quote_is_accepted(self):
        source = 'Primary Care Update organised by\r\nMedical  School. Online for Malaysian doctors.'
        training = self._training(source, {
            'title': 'Primary Care Update',
            'provider': 'Medical School',
            'country': 'Malaysian',
            'mode': 'Online',
        })
        self.assertIs(validate_evidence(training), training)

    def test_invented_quote_still_rejected(self):
        source = 'Unrelated footer text only.'
        training = self._training(source, {
            'title': 'Invented title that is absent',
            'provider': 'Medical School',
            'country': 'MY',
            'mode': 'online',
        })
        with self.assertRaises(ValueError):
            validate_evidence(training)


if __name__ == '__main__':
    unittest.main()
