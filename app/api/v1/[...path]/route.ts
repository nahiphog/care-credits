import { NextRequest, NextResponse } from 'next/server';
import { apiErrorBody, envelopeHeaders, notFoundBody, unavailableBody, type ApiErrorBody } from '@/lib/apiEnvelope';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

function backendBase() {
  return (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function isJsonContentType(value: string | null) {
  const ctype = (value || '').toLowerCase();
  return ctype.includes('application/json') || ctype.includes('+json');
}

/** Fully decode a path segment so nested encodings (%252e%252e) cannot bypass `..` checks. */
function fullyDecodeSegment(segment: string): string | null {
  let current = segment;
  // Cap iterations: reject pathological nested encodings instead of looping forever.
  for (let i = 0; i < 5; i += 1) {
    let next: string;
    try {
      next = decodeURIComponent(current);
    } catch {
      return null;
    }
    if (next === current) return current;
    current = next;
  }
  return null;
}

/** Reject path traversal / empty segments so join cannot escape `/api/v1/`. */
function safeApiPath(path: string[]): string | null {
  if (!path.length) return null;
  for (const segment of path) {
    if (!segment) return null;
    // Decode until stable so %2e%2e / %252e%252e / %2f cannot bypass literal `..` / slash checks.
    const decoded = fullyDecodeSegment(segment);
    if (
      !decoded ||
      decoded === '.' ||
      decoded === '..' ||
      decoded.includes('/') ||
      decoded.includes('\\') ||
      decoded.includes('\0')
    ) {
      return null;
    }
  }
  return path.join('/');
}

function localEnvelope(request: NextRequest, status: number, body: ApiErrorBody) {
  const id = request.headers.get('x-request-id') || body.error.request_id;
  // Match unmatched/empty `/api/v1` HEAD: probes stay bodyless.
  if (request.method === 'HEAD') {
    return new NextResponse(null, { status, headers: envelopeHeaders(id) });
  }
  return NextResponse.json(body, { status, headers: envelopeHeaders(id) });
}

async function proxy(request: NextRequest, path: string[]) {
  const rid = request.headers.get('x-request-id') || crypto.randomUUID();
  const joined = safeApiPath(path);
  if (!joined) {
    return localEnvelope(request, 404, notFoundBody(rid));
  }
  const target = `${backendBase()}/api/v1/${joined}${request.nextUrl.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (['host', 'connection', 'content-length'].includes(key.toLowerCase())) return;
    headers.set(key, value);
  });
  const discoveryRun = request.method === 'POST' && /^admin\/ingestion-jobs\/[^/]+\/run$/.test(joined);
  const timeout = AbortSignal.timeout(discoveryRun ? 240_000 : 30_000);
  const init: RequestInit = {
    method: request.method, headers, redirect: 'manual',
    signal: AbortSignal.any([request.signal, timeout]),
  };
  if (!['GET', 'HEAD'].includes(request.method)) {
    init.body = await request.arrayBuffer();
  }
  try {
    const upstream = await fetch(target, init);
    const upstreamType = upstream.headers.get('content-type');
    // Non-JSON error bodies (plain text / gateway junk) must not reach portal JSON parsers.
    // Only NTF-01 digest unsubscribe HTML errors pass through (email clients on the Next BFF);
    // other upstream HTML errors (gateway junk) still wrap as SDD JSON envelopes.
    const upstreamHtml = (upstreamType || '').toLowerCase().includes('text/html');
    const unsubscribeHtmlError = upstreamHtml && joined === 'digest/unsubscribe';
    if (upstream.status >= 400 && !isJsonContentType(upstreamType) && !unsubscribeHtmlError) {
      const code = upstream.status === 503 ? 'unavailable' : upstream.status >= 500 ? 'upstream' : 'error';
      const message =
        upstream.status === 503
          ? 'CareCredits API is unavailable.'
          : upstream.status >= 500
            ? 'CareCredits API returned a non-JSON error.'
            : 'CareCredits API returned an unexpected response.';
      const status = upstream.status >= 400 && upstream.status < 600 ? upstream.status : 502;
      return localEnvelope(request, status, apiErrorBody(code, message, rid));
    }
    // HEAD probes must stay bodyless even if an upstream mis-sends a body.
    const response = new NextResponse(request.method === 'HEAD' ? null : upstream.body, {
      status: upstream.status,
    });
    upstream.headers.forEach((value, key) => {
      // fetch may decompress; drop length/encoding/connection so clients are not truncated.
      if (['transfer-encoding', 'content-encoding', 'content-length', 'connection'].includes(key.toLowerCase())) {
        return;
      }
      response.headers.append(key, value);
    });
    if (!response.headers.get('content-type') && isJsonContentType(upstreamType)) {
      response.headers.set('Content-Type', upstreamType!);
    }
    if (!response.headers.has('x-request-id')) {
      response.headers.set('X-Request-Id', rid);
    }
    return response;
  } catch {
    if (timeout.aborted) {
      return localEnvelope(request, 504, apiErrorBody('timeout', discoveryRun
        ? 'Discovery is taking longer than expected. Refresh the run status before starting another run.'
        : 'The request took too long. Check whether it completed before trying again.', rid));
    }
    return localEnvelope(request, 503, unavailableBody(rid));
  }
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).path);
}
export async function HEAD(request: NextRequest, context: RouteContext) {
  // Proxy already skips bodies for HEAD; export so probes are not 405.
  return proxy(request, (await context.params).path);
}
export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).path);
}
export async function PUT(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).path);
}
export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).path);
}
export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, (await context.params).path);
}
