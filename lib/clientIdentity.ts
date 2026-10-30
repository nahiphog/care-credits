import { createHmac } from 'node:crypto';
import { isIP } from 'node:net';

/** Only Vercel's overwritten edge header is trusted; never relay browser signatures. */
export function forwardClientIdentity(incoming: Headers, outgoing: Headers, method: string, path: string) {
  for (const name of ['x-care-proxy-ip', 'x-care-proxy-time', 'x-care-proxy-signature']) outgoing.delete(name);
  const secret = process.env.PROXY_IDENTITY_SECRET;
  const ip = incoming.get('x-vercel-forwarded-for')?.trim();
  if (process.env.VERCEL !== '1' || !secret || !ip || !isIP(ip)) return;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const payload = [timestamp, ip, method, path].join('\n');
  outgoing.set('x-care-proxy-ip', ip);
  outgoing.set('x-care-proxy-time', timestamp);
  outgoing.set('x-care-proxy-signature', createHmac('sha256', secret).update(payload).digest('hex'));
}
