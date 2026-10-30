import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from scraper.tavily import ProviderError as HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from scraper import tavily as d
import setup_tavily
import setup_integrations


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TAVILY_API_KEY': 'test-only', 'DISCOVERY_API_TOKEN': 'operator'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_search_extract_contract_and_deduplication(self):
        replies = [
            {'results': [
                {'url': 'https://example.org/event#one', 'title': 'Course', 'content': 'Snippet'},
                {'url': 'https://example.org/event#two'},
                {'url': 'file:///etc/passwd'},
            ]},
            {'results': [{'url': 'https://example.org/event', 'raw_content': 'Event details'}]},
        ]
        with patch.object(d, 'urlopen', side_effect=[io.BytesIO(json.dumps(x).encode()) for x in replies]) as call:
            result = d.discover('cardiology', 5)
        self.assertEqual(call.call_count, 2)
        search = call.call_args_list[0].args[0]
        extract = call.call_args_list[1].args[0]
        self.assertEqual(search.full_url, 'https://api.tavily.com/search')
        self.assertIn('Malaysia medical CPD', json.loads(search.data)['query'])
        self.assertEqual(search.get_header('Authorization'), 'Bearer test-only')
        self.assertEqual(extract.full_url, 'https://api.tavily.com/extract')
        self.assertEqual(json.loads(extract.data)['urls'], ['https://example.org/event'])
        self.assertEqual(call.call_args_list[0].kwargs['timeout'], 30)
        self.assertEqual(result['sources'][0]['raw_content'], 'Event details')
        self.assertEqual(result['sources'][0]['verification_status'], 'unverified')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['warnings'], [])
        self.assertIsNone(result['usage']['tavily_credits'])
        # Per-source stamp must match provider retrieval so job-complete can persist scraper ISO.
        self.assertEqual(result['sources'][0]['retrieved_at'], result['retrieved_at'])
        self.assertTrue(result['retrieved_at'])
        self.assertNotIn('test-only', json.dumps(result))

    def test_directory_follows_one_matching_same_site_detail(self):
        listing='https://example.org/modules'
        detail='https://example.org/courses/work-related-musculoskeletal-disorders/'
        markdown=f'[View course outline]({detail})'
        replies=[{'results':[{'url':listing}]},
                 {'results':[{'url':listing,'raw_content':markdown}], 'usage':{'credits':1}},
                 {'results':[{'url':detail,'raw_content':'Medcomet online course details'}], 'usage':{'credits':1}}]
        with patch.object(d,'tavily_post',side_effect=replies) as call:
            result=d.discover('work related musculoskeletal disorders',1)
        self.assertEqual(call.call_count,3)
        self.assertEqual(result['sources'][0]['url'],d.source_url(detail))
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['usage']['tavily_credits'],2)
        self.assertEqual(result['warnings'],[])

    def test_detail_selection_rejects_external_ambiguous_and_recursive_links(self):
        source={'url':'https://example.org/modules','raw_content':'[Work related course](https://evil.org/courses/work-related/)'}
        self.assertIsNone(d.matching_detail_link(source,'work related'))
        source['raw_content']='[Work related A](/courses/work-related-a/) [Work related B](/courses/work-related-b/)'
        self.assertIsNone(d.matching_detail_link(source,'work related'))
        source['url']='https://example.org/courses/existing/'
        self.assertIsNone(d.matching_detail_link(source,'work related A'))
        source={'url':'https://example.org/modules','raw_content':'[Work related](http://127.0.0.1/courses/work-related/)'}
        self.assertIsNone(d.matching_detail_link(source,'work related'))
        source['raw_content']='[Work related](https://[broken/courses/work-related/)'
        self.assertIsNone(d.matching_detail_link(source,'work related'))

    def test_failed_detail_fetch_retains_directory_and_does_not_retry(self):
        listing='https://example.org/modules'
        replies=[{'results':[{'url':listing}]}, {'results':[{'url':listing,'raw_content':'[Work related](/courses/work-related/)'}]}, HTTPException(504,'Unavailable')]
        with patch.object(d,'tavily_post',side_effect=replies) as call:
            result=d.discover('work related',1)
        self.assertEqual(call.call_count,3)
        self.assertEqual(result['sources'][0]['url'],listing)
        self.assertIn('directory evidence retained',result['warnings'][0])

    def test_discover_records_reported_credits(self):
        replies = [
            {'results': [{'url': 'https://example.org/event', 'title': 'Course', 'content': 'Snippet'}], 'usage': {'credits': 1}},
            {'results': [{'url': 'https://example.org/event', 'raw_content': 'Event details'}], 'usage': {'credits': 2}},
        ]
        with patch.object(d, 'urlopen', side_effect=[io.BytesIO(json.dumps(x).encode()) for x in replies]):
            result = d.discover('cardiology', 5)
        self.assertEqual(result['usage']['tavily_credits'], 3)

    def test_reported_credits_rejects_bool_nan_inf(self):
        self.assertIsNone(d.reported_credits({'usage': {'credits': True}}))
        self.assertIsNone(d.reported_credits({'usage': {'credits': False}}))
        self.assertIsNone(d.reported_credits({'usage': {'credits': float('nan')}}))
        self.assertIsNone(d.reported_credits({'usage': {'credits': float('inf')}}))
        self.assertEqual(d.reported_credits({'usage': {'credits': 1.5}}), 1.5)

    def test_empty_search_skips_extract(self):
        with patch.object(d, 'tavily_post', return_value={'results': []}) as call:
            result = d.discover('cardiology')
            self.assertEqual(result['sources'], [])
            self.assertIn('No source pages matched', result['warnings'][0])
            call.assert_called_once()

    def test_extraction_failure_keeps_snippets(self):
        source = {'results': [{'url': 'https://example.org/event', 'content': 'Retain me'}]}
        for failure in [HTTPException(504, 'Unavailable'), {'results': [], 'failed_results': [{}]}]:
            with self.subTest(failure=failure), patch.object(d, 'tavily_post', side_effect=[source, failure]):
                result = d.discover('cardiology')
                self.assertEqual(result['sources'][0]['snippet'], 'Retain me')
                self.assertEqual(result['sources'][0]['extraction_status'], 'failed')
                self.assertIsNone(result['sources'][0]['raw_content'])
                self.assertTrue(result['warnings'])

    def test_missing_key_makes_no_call(self):
        with patch.dict(os.environ, {'TAVILY_API_KEY': ''}), patch.object(d, 'urlopen') as call:
            with self.assertRaises(HTTPException) as error:
                d.discover('cardiology')
            self.assertEqual(error.exception.status_code, 503)
            self.assertIn('setup_integrations.py', error.exception.detail)
            call.assert_not_called()

    def test_url_filter(self):
        for url in ['javascript:alert(1)', 'http://localhost/a', 'https://x.local/a', 'http://127.0.0.1/a', 'https://user:pass@example.org/a', 'http://[::1]/', 'https://example.org:8080/a']:
            self.assertIsNone(d.source_url(url), url)

    def test_upstream_errors_sanitized(self):
        for status, expected in [(401, 503), (403, 503), (429, 429), (432, 429), (433, 429), (500, 502)]:
            error = HTTPError('https://api.tavily.com/search', status, 'secret-provider-body', {}, None)
            with self.subTest(status=status), patch.object(d, 'urlopen', side_effect=error):
                with self.assertRaises(HTTPException) as caught:
                    d.tavily_post('search', {}, 'test-only')
                self.assertEqual(caught.exception.status_code, expected)
                self.assertNotIn('secret', caught.exception.detail)
        with patch.object(d, 'urlopen', side_effect=URLError('private-details')):
            with self.assertRaises(HTTPException) as caught:
                d.tavily_post('search', {}, 'test-only')
            self.assertEqual(caught.exception.status_code, 504)

    def test_invalid_provider_response(self):
        for body in [b'not json', b'[]', b'{"results": null}']:
            with patch.object(d, 'urlopen', return_value=io.BytesIO(body)):
                with self.assertRaises(HTTPException) as caught:
                    d.tavily_post('search', {}, 'test-only')
                self.assertEqual(caught.exception.status_code, 502)

    def test_setup_preserves_other_settings_and_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.sample').write_text('DB_NAME=keep\nTAVILY_API_KEY=\nDISCOVERY_API_TOKEN=\n')
            with patch.object(setup_tavily, '__file__', str(root / 'scripts' / 'setup_tavily.py')), patch.object(setup_tavily.getpass, 'getpass', return_value='tvly-test-only'), patch('sys.stdout', new_callable=io.StringIO) as output:
                setup_tavily.main()
                first = (root / '.env').read_text()
                setup_tavily.main()
                self.assertEqual(first, (root / '.env').read_text())
                self.assertIn('DB_NAME=keep', first)
                self.assertIn('TAVILY_API_KEY=tvly-test-only', first)
                self.assertNotIn('tvly-test-only', output.getvalue())
                if os.name != 'nt':  # Windows uses inherited ACLs, not POSIX mode bits.
                    self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)

    def test_setup_integrations_records_model_identity(self):
        sample = (
            'TAVILY_API_KEY=\nMODEL_API_KEY=\nTYPESAFE_API_KEY=\nMODEL_ID=\n'
            'MODEL_WEIGHTS_URL=\nMODEL_LICENSE_URL=\nMODEL_PUBLISHER=\nMODEL_HOST=\n'
            'MODEL_BASE_URL=\nMODEL_MAX_INPUT_CHARS=\nMODEL_MAX_OUTPUT_TOKENS=\n'
            'MODEL_OPEN_WEIGHT_CONFIRMED=false\n'
        )
        answers = iter([
            'Qwen/Qwen3-test',
            'https://huggingface.co/Qwen/Qwen3-test',
            'https://huggingface.co/Qwen/Qwen3-test/blob/main/LICENSE',
            'Qwen',
            'Nebius Token Factory',
            'https://api.tokenfactory.nebius.com/v1',
            '12000',
            '4000',
            'yes',
        ])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.sample').write_text(sample)
            with patch.object(setup_integrations, '__file__', str(root / 'scripts' / 'setup_integrations.py')), patch.object(
                setup_integrations.getpass, 'getpass', return_value='sk-test-only'
            ), patch.object(setup_integrations, 'input', side_effect=lambda prompt: next(answers)), patch(
                'sys.stdout', new_callable=io.StringIO
            ) as output:
                setup_integrations.main()
            saved = (root / '.env').read_text()
            self.assertIn('MODEL_ID=Qwen/Qwen3-test', saved)
            self.assertIn('MODEL_PUBLISHER=Qwen', saved)
            self.assertIn('MODEL_HOST=Nebius Token Factory', saved)
            self.assertIn('MODEL_OPEN_WEIGHT_CONFIRMED=true', saved)
            self.assertIn('MODEL_BASE_URL=https://api.tokenfactory.nebius.com/v1', saved)
            self.assertIn('MODEL_MAX_INPUT_CHARS=12000', saved)
            self.assertIn('MODEL_MAX_OUTPUT_TOKENS=4000', saved)
            self.assertIn('MODEL_API_KEY=sk-test-only', saved)
            self.assertNotIn('sk-test-only', output.getvalue())
            if os.name != 'nt':  # Windows uses inherited ACLs, not POSIX mode bits.
                self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)

    def test_setup_integrations_leaves_open03_identity_blank(self):
        sample = (
            'TAVILY_API_KEY=\nMODEL_API_KEY=\nTYPESAFE_API_KEY=\nMODEL_ID=\n'
            'MODEL_WEIGHTS_URL=\nMODEL_LICENSE_URL=\nMODEL_PUBLISHER=\nMODEL_HOST=\n'
            'MODEL_BASE_URL=\nMODEL_MAX_INPUT_CHARS=\nMODEL_MAX_OUTPUT_TOKENS=\n'
            'MODEL_OPEN_WEIGHT_CONFIRMED=false\n'
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.sample').write_text(sample)
            with patch.object(setup_integrations, '__file__', str(root / 'scripts' / 'setup_integrations.py')), patch.object(
                setup_integrations.getpass, 'getpass', return_value=''
            ), patch.object(setup_integrations, 'input', return_value=''), patch('sys.stdout', new_callable=io.StringIO):
                setup_integrations.main()
            saved = (root / '.env').read_text()
            self.assertIn('MODEL_ID=\n', saved)
            self.assertIn('MODEL_PUBLISHER=\n', saved)
            self.assertIn('MODEL_HOST=\n', saved)
            self.assertIn('MODEL_MAX_INPUT_CHARS=\n', saved)
            self.assertNotIn('Qwen/Qwen3-30B-A3B-Instruct-2507', saved)
            self.assertNotIn('Nebius Token Factory', saved)
            self.assertIn('MODEL_OPEN_WEIGHT_CONFIRMED=false', saved)
            self.assertNotIn('MODEL_OPEN_WEIGHT_CONFIRMED=true', saved)
            self.assertIn('MODEL_API_KEY=\n', saved)

    def test_setup_integrations_no_clears_prior_open_weight_confirm(self):
        sample = (
            'TAVILY_API_KEY=\nMODEL_API_KEY=\nTYPESAFE_API_KEY=\nMODEL_ID=\n'
            'MODEL_WEIGHTS_URL=\nMODEL_LICENSE_URL=\nMODEL_PUBLISHER=\nMODEL_HOST=\n'
            'MODEL_BASE_URL=\nMODEL_MAX_INPUT_CHARS=\nMODEL_MAX_OUTPUT_TOKENS=\n'
            'MODEL_OPEN_WEIGHT_CONFIRMED=true\n'
        )
        answers = iter(['', '', '', '', '', '', '', '', 'no'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.sample').write_text(sample)
            with patch.object(setup_integrations, '__file__', str(root / 'scripts' / 'setup_integrations.py')), patch.object(
                setup_integrations.getpass, 'getpass', return_value=''
            ), patch.object(setup_integrations, 'input', side_effect=lambda prompt: next(answers)), patch(
                'sys.stdout', new_callable=io.StringIO
            ):
                setup_integrations.main()
            saved = (root / '.env').read_text()
            self.assertIn('MODEL_OPEN_WEIGHT_CONFIRMED=false', saved)
            self.assertNotIn('MODEL_OPEN_WEIGHT_CONFIRMED=true', saved)

    def test_repo_env_sample_leaves_open03_identity_blank(self):
        sample = (Path(__file__).resolve().parents[2] / '.env.sample').read_text()
        self.assertIn('MODEL_ID=\n', sample)
        self.assertIn('MODEL_PUBLISHER=\n', sample)
        self.assertIn('MODEL_HOST=\n', sample)
        self.assertIn('MODEL_MAX_INPUT_CHARS=\n', sample)
        self.assertIn('MODEL_MAX_OUTPUT_TOKENS=\n', sample)
        self.assertNotIn('Qwen/Qwen3-30B-A3B-Instruct-2507', sample)
        self.assertNotIn('Nebius Token Factory', sample)
        self.assertNotIn('huggingface.co/Qwen', sample)
        self.assertIn('MODEL_OPEN_WEIGHT_CONFIRMED=false', sample)


if __name__ == '__main__':
    unittest.main()
