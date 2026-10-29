"""Tests for the upgraded extraction pipeline: cleaning, JSON repair, grouping, week stamping."""
import json
import os
import unittest
from unittest.mock import patch

import httpx

from scraper.extraction import (
    clean_source_text,
    sanitize_hidden_chars,
    _parse_llm_trainings,
    group_candidates_by_week,
    heuristic_extract,
    extract_training,
    ExtractionError,
)
from shared.contracts import Training, validate_evidence


class CleanSourceTextTests(unittest.TestCase):
    def test_short_text_is_untouched_except_hidden_chars(self):
        raw = 'Primary care CME in Kuala Lumpur\u200b 2026-06-12.'
        cleaned = clean_source_text(raw, max_chars=12000)
        self.assertNotIn('\u200b', cleaned)
        self.assertIn('Primary care CME in Kuala Lumpur', cleaned)

    def test_boilerplate_pruned_only_when_long_and_signal_kept(self):
        signal = 'CPD conference 2026-06-12 in Kuala Lumpur venue Menara.'
        filler = 'Cookie policy and privacy policy. Follow us on Facebook. ' * 400
        raw = filler + '\n' + signal + '\n' + filler
        cleaned = clean_source_text(raw, max_chars=2000)
        self.assertIn(signal, cleaned)
        self.assertLessEqual(len(cleaned), 2000)
        # The kept signal line is verbatim so evidence quotes still validate.
        self.assertIn('2026-06-12', cleaned)

    def test_sanitize_preserves_visible_substrings(self):
        raw = 'Regi\u200bster for the CPD\ufeff course'
        self.assertEqual(sanitize_hidden_chars(raw), 'Register for the CPD course')


class ParseLlmTrainingsTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(_parse_llm_trainings('{"trainings": [{"title": "x"}]}'), [{'title': 'x'}])

    def test_code_fence_and_prose(self):
        raw = 'Here you go:\n```json\n{"trainings": [{"title": "x"}]}\n```'
        self.assertEqual(_parse_llm_trainings(raw), [{'title': 'x'}])

    def test_trailing_comma_repair(self):
        raw = '{"trainings": [{"title": "x"},]}'
        self.assertEqual(_parse_llm_trainings(raw), [{'title': 'x'}])

    def test_bare_array(self):
        self.assertEqual(_parse_llm_trainings('[{"title": "x"}]'), [{'title': 'x'}])

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            _parse_llm_trainings('not json at all')


class GroupByWeekTests(unittest.TestCase):
    def test_groups_week_key_first_and_sorted(self):
        rows = [
            {'week_key': '2026-W46', 'start_date': '2026-11-14', 'source_key': 'b'},
            {'week_key': '2026-W43', 'start_date': '2026-10-20', 'source_key': 'a'},
            {'week_key': '2026-W46', 'start_date': '2026-11-10', 'source_key': 'c'},
        ]
        grouped = group_candidates_by_week(rows)
        self.assertEqual(list(grouped), ['2026-W43', '2026-W46'])
        self.assertEqual([r['source_key'] for r in grouped['2026-W46']], ['c', 'b'])

    def test_derives_week_key_when_missing(self):
        grouped = group_candidates_by_week([{'start_date': '2026-11-14'}])
        self.assertEqual(list(grouped), ['2026-W46'])


class HeuristicWeekStampTests(unittest.TestCase):
    def test_week_and_source_key_stamped(self):
        rows = heuristic_extract({
            'url': 'https://disruptive-doctors.com/dd-con-2026',
            'title': 'DD CON 2026 Conference',
            'raw_content': (
                'DD CON 2026 Conference organised by Disruptive Doctors in Kuala Lumpur, Malaysia.\n'
                'Conference dates 2026-09-04. In-person primary care conference.'
            ),
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['week_key'], '2026-W36')
        self.assertTrue(rows[0]['source_key'])
        self.assertTrue(rows[0]['scrape_week_key'])

    def test_registration_url_extracted_with_verbatim_evidence(self):
        rows = heuristic_extract({
            'url': 'https://afpm.org.my/primary-care-2026',
            'title': 'Primary Care Update 2026',
            'raw_content': (
                'Primary Care Update 2026 organised by Academy of Family Physicians in Kuala Lumpur, Malaysia. '
                'Conference 2026-06-12. Register at https://afpm.org.my/register now.'
            ),
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['registration_url'], 'https://afpm.org.my/register')
        self.assertIn('registration_url', rows[0]['evidence'])
        self.assertIn(rows[0]['evidence']['registration_url'], rows[0]['source_text'])

    def test_points_fee_difficulty_stay_conservative(self):
        # Backward-compatible contract: heuristic never infers points/fee/difficulty.
        rows = heuristic_extract({
            'url': 'https://example.org/primary-care-update',
            'title': 'Primary Care Update',
            'raw_content': (
                'Primary Care Update organised by Medical School in Kuala Lumpur, Malaysia. '
                'Conference 2026-06-12. 8 CPD points. Fee MYR 350. Sounds advanced.'
            ),
        })
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['points'])
        self.assertIsNone(rows[0]['fee'])
        self.assertIsNone(rows[0]['difficulty'])


class ExtractTrainingResilienceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'MODEL_ID': 'test/open-weight-model', 'MODEL_API_KEY': 'test-secret',
            'MODEL_WEIGHTS_URL': 'https://example.org/weights', 'MODEL_LICENSE_URL': 'https://example.org/license',
            'MODEL_OPEN_WEIGHT_CONFIRMED': 'true', 'MODEL_BASE_URL': 'https://example.org/v1',
            'MODEL_MAX_INPUT_CHARS': '12000', 'MODEL_MAX_OUTPUT_TOKENS': '4000',
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def _client(self, rows):
        def handler(request):
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'trainings': rows})}}]})
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_one_bad_session_does_not_drop_the_valid_ones(self):
        text = (
            'Saturday clinic skills by Melaka CME Group in Malacca, Malaysia. 2026-05-16. '
            'Sunday clinic skills by Melaka CME Group in Malacca, Malaysia. 2026-05-17.'
        )
        source = {'url': 'https://melakacme.my/weekend', 'raw_content': text}
        valid = {
            'title': 'Saturday clinic skills', 'provider': 'Melaka CME Group', 'mode': 'in_person',
            'country': 'MY', 'city': 'Malacca', 'start_date': '2026-05-16',
            'evidence': {k: text for k in ['title', 'provider', 'mode', 'country', 'city', 'start_date']},
        }
        # Invalid: points without credit_label -> Training constraint failure.
        bad = {**valid, 'title': 'Sunday clinic skills', 'start_date': '2026-05-17', 'points': 5}
        with self._client([valid, bad]) as client:
            result = extract_training(source, client)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'Saturday clinic skills')
        self.assertEqual(result[0]['week_key'], '2026-W20')
        self.assertTrue(result[0]['source_key'])

    def test_single_bad_row_still_raises(self):
        text = 'Primary care seminar. Provider: Medical School. Online for Malaysian doctors.'
        source = {'url': 'https://example.org/event', 'raw_content': text}
        bad = {
            'title': 'Primary care seminar', 'provider': 'Medical School', 'mode': 'online', 'country': 'MY',
            'points': 10, 'credit_label': 'CPD',
            'evidence': {k: text for k in ['title', 'provider', 'mode', 'country']},
        }
        with self._client([bad]) as client:
            with self.assertRaises(ExtractionError):
                extract_training(source, client)

    def test_full_source_text_retained_for_evidence(self):
        # Even if the LLM window is pruned, source_text keeps the full page so evidence validates.
        text = 'Primary care seminar. Provider: Medical School. Online for Malaysian doctors.'
        source = {'url': 'https://example.org/event', 'raw_content': text}
        row = {
            'title': 'Primary care seminar', 'provider': 'Medical School', 'mode': 'online', 'country': 'MY',
            'evidence': {k: text for k in ['title', 'provider', 'mode', 'country']},
        }
        with self._client([row]) as client:
            result = extract_training(source, client)
        training = Training(**{k: v for k, v in result[0].items() if k in Training.model_fields})
        validate_evidence(training)
        self.assertEqual(result[0]['scrape_week_key'], training.scrape_week_key)


if __name__ == '__main__':
    unittest.main()
