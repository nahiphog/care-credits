import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jev import api_key, decide_existence, JevError


CANDIDATE = {
    'title': 'Primary Care Update 2026',
    'provider': 'AFPM',
    'start_date': '2026-06-01',
    'city': 'Kuala Lumpur',
    'mode': 'in_person',
    'source_url': 'https://example.org/new',
}
MATCH = {
    'id': 'course-1',
    'title': 'Primary Care Update 2026',
    'provider': 'AFPM',
    'start_date': '2026-06-01',
    'city': 'Kuala Lumpur',
    'mode': 'in_person',
    'source_url': 'https://example.org/old',
}


class FakeChoice:
    def __init__(self, choice, confidence, probabilities):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = probabilities


class FakeClient:
    def __init__(self, answer):
        self.answer = answer
        self.called = None

    def system_one(self, **kwargs):
        self.called = kwargs
        return SimpleNamespace(choices={'existence': self.answer})


class JevTests(unittest.TestCase):
    def test_no_matches_is_new_without_api(self):
        result = decide_existence(CANDIDATE, [])
        self.assertEqual(result['decision'], 'new')
        self.assertEqual(result['confidence'], 1.0)

    def test_missing_key_is_uncertain(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}, clear=False):
            with patch('jev.keyfile_path') as keyfile:
                keyfile.return_value.is_file.return_value = False
                result = decide_existence(CANDIDATE, [MATCH])
        self.assertEqual(result['decision'], 'uncertain')
        self.assertIn('TYPESAFE_API_KEY', result['warning'])

    def test_keyfile_used_when_env_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'key'
            path.write_text('ts_from_file\n')
            with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}, clear=False):
                with patch('jev.keyfile_path', return_value=path):
                    self.assertEqual(api_key(), 'ts_from_file')

    def test_sdk_exists_above_floor(self):
        client = FakeClient(FakeChoice('exists', 0.91, {'exists': 0.91, 'new': 0.05, 'uncertain': 0.04}))
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            result = decide_existence(CANDIDATE, [MATCH], client=client)
        self.assertEqual(result['decision'], 'exists')
        self.assertEqual(result['matched_session_id'], 'course-1')
        self.assertEqual(client.called['model'], 'jev-latest')
        self.assertIn('existence', client.called['questions'])

    def test_low_confidence_forced_uncertain(self):
        client = FakeClient(FakeChoice('exists', 0.4, {'exists': 0.4, 'new': 0.3, 'uncertain': 0.3}))
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            result = decide_existence(CANDIDATE, [MATCH], client=client)
        self.assertEqual(result['decision'], 'uncertain')
        self.assertIn('floor', result['warning'])

    def test_confidence_floor_clamps_out_of_range(self):
        from jev import confidence_floor, unit_interval

        with patch.dict(os.environ, {'JEV_CONFIDENCE_FLOOR': '2.5'}):
            self.assertEqual(confidence_floor(), 1.0)
        with patch.dict(os.environ, {'JEV_CONFIDENCE_FLOOR': '-0.2'}):
            self.assertEqual(confidence_floor(), 0.0)
        with patch.dict(os.environ, {'JEV_CONFIDENCE_FLOOR': 'nan'}):
            self.assertEqual(confidence_floor(), 0.7)
        # Bool must not become 1.0 / 0.0 via float(True/False).
        self.assertEqual(unit_interval(True, 0.0), 0.0)
        self.assertEqual(unit_interval(False, 0.3), 0.3)

    def test_bool_confidence_forced_uncertain(self):
        """SDK bool confidence must not pass the floor as float(True)==1.0."""
        client = FakeClient(FakeChoice('new', True, {'new': True, 'exists': False, 'uncertain': False}))
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            result = decide_existence(CANDIDATE, [MATCH], client=client)
        self.assertEqual(result['decision'], 'uncertain')
        self.assertEqual(result['confidence'], 0.0)
        self.assertIn('floor', result['warning'])

    def test_out_of_range_confidence_is_normalized(self):
        client = FakeClient(FakeChoice('new', 1.4, {'exists': 0.0, 'new': 1.4, 'uncertain': -0.2}))
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            result = decide_existence(CANDIDATE, [MATCH], client=client)
        self.assertEqual(result['decision'], 'new')
        self.assertEqual(result['confidence'], 1.0)
        self.assertEqual(result['probabilities']['new'], 1.0)
        self.assertEqual(result['probabilities']['uncertain'], 0.0)

    def test_sdk_picks_matched_id(self):
        second = {**MATCH, 'id': 'course-2', 'title': 'Primary Care Update Evening'}
        client = FakeClient(FakeChoice('exists', 0.88, {'exists': 0.88, 'new': 0.08, 'uncertain': 0.04}))
        client.answer_matched = FakeChoice('course-2', 0.8, {'course-2': 0.8, 'course-1': 0.15, 'none': 0.05})

        def system_one(**kwargs):
            client.called = kwargs
            return SimpleNamespace(choices={'existence': client.answer, 'matched': client.answer_matched})

        client.system_one = system_one
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test'}):
            result = decide_existence(CANDIDATE, [MATCH, second], client=client)
        self.assertEqual(result['decision'], 'exists')
        self.assertEqual(result['matched_session_id'], 'course-2')
        self.assertIn('matched', client.called['questions'])

    def test_multi_match_exists_without_pick_is_uncertain(self):
        second = {**MATCH, 'id': 'course-2', 'title': 'Primary Care Update Evening'}
        client = FakeClient(FakeChoice('exists', 0.9, {'exists': 0.9, 'new': 0.05, 'uncertain': 0.05}))
        client.answer_matched = FakeChoice('none', 0.7, {'none': 0.7, 'course-1': 0.2, 'course-2': 0.1})

        def system_one(**kwargs):
            return SimpleNamespace(choices={'existence': client.answer, 'matched': client.answer_matched})

        client.system_one = system_one
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test'}):
            result = decide_existence(CANDIDATE, [MATCH, second], client=client)
        self.assertEqual(result['decision'], 'uncertain')
        self.assertIsNone(result['matched_session_id'])
        self.assertIn('valid match id', result['warning'])

    def test_sdk_error_sanitized(self):
        class Boom:
            def system_one(self, **kwargs):
                err = RuntimeError('secret-provider-body')
                err.status_code = 401
                raise err

        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'ts_test'}):
            with self.assertRaises(JevError) as caught:
                decide_existence(CANDIDATE, [MATCH], client=Boom())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn('secret', caught.exception.detail)


if __name__ == '__main__':
    unittest.main()
