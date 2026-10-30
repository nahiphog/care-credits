import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { forwardClientIdentity } from '../lib/clientIdentity.ts';

test('only the platform header is signed and browser signatures are overwritten', () => {
  const prior = { ...process.env };
  try {
    process.env.VERCEL = '1'; process.env.PROXY_IDENTITY_SECRET = 'test-only';
    const incoming = new Headers({ 'x-vercel-forwarded-for': '203.0.113.7', 'x-forwarded-for': '1.1.1.1', 'x-care-proxy-ip': '2.2.2.2', 'x-care-proxy-signature': 'forged' });
    const outgoing = new Headers(incoming);
    forwardClientIdentity(incoming, outgoing, 'POST', '/api/v1/auth/login');
    assert.equal(outgoing.get('x-care-proxy-ip'), '203.0.113.7');
    const message = [outgoing.get('x-care-proxy-time'), '203.0.113.7', 'POST', '/api/v1/auth/login'].join('\n');
    assert.equal(outgoing.get('x-care-proxy-signature'), createHmac('sha256','test-only').update(message).digest('hex'));
    for (const bad of ['', '1.1.1.1, 2.2.2.2', 'not-an-address']) {
      incoming.set('x-vercel-forwarded-for', bad);
      forwardClientIdentity(incoming, outgoing, 'POST', '/api/v1/auth/login');
      assert.equal(outgoing.get('x-care-proxy-signature'), null);
    }
    incoming.set('x-vercel-forwarded-for','203.0.113.7'); delete process.env.VERCEL;
    forwardClientIdentity(incoming, outgoing, 'POST', '/api/v1/auth/login');
    assert.equal(outgoing.get('x-care-proxy-ip'), null);
  } finally { process.env = prior; }
});
