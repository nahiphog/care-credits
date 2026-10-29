"""Runtime check that Next /api error helpers emit SDD envelopes."""
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENVELOPE = ROOT / 'frontend' / 'lib' / 'apiEnvelope.ts'


class FrontendApiEnvelopeTests(unittest.TestCase):
    def test_api_envelope_helpers_return_sdd_shape(self):
        self.assertTrue(ENVELOPE.is_file())
        script = f"""
import {{ notFoundBody, unavailableBody, apiErrorBody, envelopeHeaders, JSON_CONTENT_TYPE }} from {json.dumps(str(ENVELOPE))};
const a = notFoundBody('rid-404');
const b = unavailableBody('rid-503');
const c = apiErrorBody('forbidden', 'Nope.', 'rid-403');
const h = envelopeHeaders('rid-h');
if (a.error.code !== 'not_found' || a.error.request_id !== 'rid-404') throw new Error(JSON.stringify(a));
if (b.error.code !== 'unavailable' || !b.error.message.includes('unavailable')) throw new Error(JSON.stringify(b));
if (c.error.code !== 'forbidden' || c.error.message !== 'Nope.') throw new Error(JSON.stringify(c));
if (h['Content-Type'] !== JSON_CONTENT_TYPE || h['X-Request-Id'] !== 'rid-h') throw new Error(JSON.stringify(h));
console.log(JSON.stringify({{ ok: true, keys: Object.keys(a.error).sort() }}));
"""
        result = subprocess.run(
            ['node', '--experimental-strip-types', '--input-type=module', '-e', script],
            cwd=str(ROOT / 'frontend'),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['keys'], ['code', 'message', 'request_id'])

    def test_api_routes_use_shared_envelope_helpers(self):
        unmatched = (ROOT / 'frontend' / 'app' / 'api' / '[...path]' / 'route.ts').read_text(encoding='utf-8')
        empty_v1 = (ROOT / 'frontend' / 'app' / 'api' / 'v1' / 'route.ts').read_text(encoding='utf-8')
        proxy = (ROOT / 'frontend' / 'app' / 'api' / 'v1' / '[...path]' / 'route.ts').read_text(encoding='utf-8')
        ready = (ROOT / 'frontend' / 'app' / 'health' / 'ready' / 'route.ts').read_text(encoding='utf-8')
        envelope = ENVELOPE.read_text(encoding='utf-8')
        self.assertIn('JSON_CONTENT_TYPE', envelope)
        self.assertIn('envelopeHeaders', envelope)
        self.assertIn("from '@/lib/apiEnvelope'", unmatched)
        self.assertIn('notFoundBody', unmatched)
        self.assertIn('envelopeHeaders', unmatched)
        self.assertIn('export async function HEAD', unmatched)
        self.assertIn('new NextResponse(null', unmatched)
        self.assertIn("from '@/lib/apiEnvelope'", empty_v1)
        self.assertIn('notFoundBody', empty_v1)
        self.assertIn('envelopeHeaders', empty_v1)
        self.assertIn('export async function HEAD', empty_v1)
        self.assertIn('new NextResponse(null', empty_v1)
        self.assertIn("from '@/lib/apiEnvelope'", proxy)
        self.assertIn('unavailableBody', proxy)
        self.assertIn('apiErrorBody', proxy)
        self.assertIn('envelopeHeaders', proxy)
        self.assertIn('notFoundBody', proxy)
        self.assertIn('safeApiPath', proxy)
        self.assertIn('fullyDecodeSegment', proxy)
        self.assertIn("decoded === '..'", proxy)
        # Encoded traversal (%2e%2e / nested %252e%252e / %2f) must not bypass literal segment checks.
        self.assertIn('decodeURIComponent', proxy)
        self.assertIn('%252e%252e', proxy)
        # Proxy body-skip already treats HEAD like GET; export so probes are not 405.
        self.assertIn('export async function HEAD', proxy)
        # Local proxy errors keep HEAD bodyless (parity with unmatched/empty /api/v1).
        self.assertIn('localEnvelope', proxy)
        self.assertIn("request.method === 'HEAD'", proxy)
        self.assertIn('new NextResponse(null', proxy)
        # Decompressed upstream bodies must not keep a stale content-length.
        self.assertIn("'content-length'", proxy)
        self.assertIn("'connection'", proxy)
        # Non-JSON upstream errors become SDD JSON envelopes with explicit Content-Type,
        # except NTF-01 digest unsubscribe HTML errors (path-scoped; gateway HTML still wraps).
        self.assertIn('isJsonContentType', proxy)
        self.assertIn('upstreamHtml', proxy)
        self.assertIn('unsubscribeHtmlError', proxy)
        self.assertIn("joined === 'digest/unsubscribe'", proxy)
        self.assertIn('text/html', proxy)
        self.assertIn("from '@/lib/apiEnvelope'", ready)
        self.assertIn('unavailableBody', ready)
        self.assertIn('envelopeHeaders', ready)
        self.assertIn("payload.status !== 'ready'", ready)
        self.assertIn('x-request-id', ready)


if __name__ == '__main__':
    unittest.main()
