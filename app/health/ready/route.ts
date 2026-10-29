import { NextRequest } from 'next/server';
import { envelopeHeaders, unavailableBody } from '@/lib/apiEnvelope';

export const dynamic = 'force-dynamic';

function backendBase() {
  return (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

export async function GET(request: NextRequest) {
  const rid = request.headers.get('x-request-id') || crypto.randomUUID();
  try {
    const response = await fetch(backendBase() + '/health/ready', { cache: 'no-store' });
    const payload = await response.json().catch(() => null);
    // Only claim ready when the backend HTTP status and body both say ready.
    if (!response.ok || !payload || payload.status !== 'ready') {
      return Response.json(unavailableBody(rid), {
        status: 503,
        headers: envelopeHeaders(rid),
      });
    }
    return Response.json(
      { status: 'ready', backend: 'ready' },
      { headers: envelopeHeaders(rid) },
    );
  } catch {
    return Response.json(unavailableBody(rid), {
      status: 503,
      headers: envelopeHeaders(rid),
    });
  }
}
