import unittest
from unittest.mock import patch
import httpx
from scraper.provider_pages import fetch_public_page
from scraper.tavily import discover


class ProviderPageTests(unittest.TestCase):
    def test_adapter_drops_scripts_and_keeps_course_links(self):
        html = '<script>private script</script><h1>Public course</h1><a href="/courses/work-related">Work related</a>'
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html, headers={'content-type':'text/html'}))) as client:
            text = fetch_public_page('https://cpdonline.my/doctor-cpd-modules', client)
        self.assertNotIn('private script', text)
        self.assertIn('[Work related](/courses/work-related)', text)

    def test_unregistered_or_private_urls_never_fetch(self):
        def unexpected(request):
            self.fail('Unexpected fetch')
        with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
            for url in ['https://evil.org/courses/a', 'https://127.0.0.1/courses/a',
                        'https://cpdonline.my/login', 'https://cpdonline.my/courses/a?token=secret',
                        'https://user:secret@cpdonline.my/courses/a', 'http://cpdonline.my/courses/a']:
                self.assertIsNone(fetch_public_page(url, client))

    def test_cross_host_redirect_rejected_and_loops_bounded(self):
        for target, expected in [('https://evil.org/courses/a', 1), ('/courses/a', 3)]:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(302, headers={'location':target})
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                self.assertIsNone(fetch_public_page('https://cpdonline.my/courses/a', client))
            self.assertEqual(len(calls), expected)

    def test_size_status_and_content_type_limits(self):
        for status, mime, text in [(200,'text/html','x'*250001),(403,'text/html','private'),(200,'application/json','{}')]:
            with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status,text=text,headers={'content-type':mime}))) as client:
                self.assertIsNone(fetch_public_page('https://cpdonline.my/courses/a',client))

    def test_directory_fallback_recovers_missing_links_without_more_tavily_calls(self):
        listing='https://cpdonline.my/doctor-cpd-modules'
        detail='https://cpdonline.my/courses/work-related'
        replies=[{'results':[{'url':listing}]},{'results':[{'url':listing,'raw_content':'Directory without links'}]}]
        with patch.dict('os.environ',{'TAVILY_API_KEY':'test'}), patch('scraper.tavily.tavily_post',side_effect=replies) as provider, patch('scraper.tavily.fetch_public_page',side_effect=['[Work related](/courses/work-related)','Public details']):
            result=discover('work related',1)
        self.assertEqual(provider.call_count,2)
        self.assertEqual(result['sources'][0]['url'],detail)
        self.assertEqual(result['warnings'],[])

    def test_failed_tavily_detail_is_recovered_by_public_adapter(self):
        url='https://cpdonline.my/courses/work-related'
        with patch.dict('os.environ',{'TAVILY_API_KEY':'test'}), patch('scraper.tavily.tavily_post',return_value={'results':[]}), patch('scraper.tavily.fetch_public_page',return_value='Public details'):
            result=discover(url,1)
        self.assertEqual(result['sources'][0]['extraction_status'],'success')
        self.assertEqual(result['warnings'],[])
