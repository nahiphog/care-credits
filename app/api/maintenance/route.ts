import { timingSafeEqual } from 'node:crypto';
import { apiErrorBody, envelopeHeaders } from '@/lib/apiEnvelope';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function GET(request: Request) {
  const id = crypto.randomUUID();
  const secret = process.env.CRON_SECRET || '';
  const supplied = request.headers.get('authorization') || '';
  const expected = `Bearer ${secret}`;
  const authorized = secret.length > 0 && Buffer.byteLength(supplied) === Buffer.byteLength(expected)
    && timingSafeEqual(Buffer.from(supplied), Buffer.from(expected));
  if (!authorized) return Response.json(apiErrorBody('unauthenticated', 'Maintenance authorization required.', id), { status: 401, headers: envelopeHeaders(id) });
  const base = (process.env.BACKEND_URL || '').replace(/\/$/, '');
  if (!base) return Response.json(apiErrorBody('unavailable', 'Maintenance backend is unavailable.', id), { status: 503, headers: envelopeHeaders(id) });
  try {
    const response = await fetch(base + '/internal/v1/maintenance', {
      headers: { Authorization: expected }, cache: 'no-store', signal: AbortSignal.timeout(45_000),
    });
    const body = await response.json();
    return Response.json(body, { status: response.status, headers: envelopeHeaders(id) });
  } catch {
    return Response.json(apiErrorBody('unavailable', 'Maintenance could not complete. Check the server logs.', id), { status: 503, headers: envelopeHeaders(id) });
  }
}
