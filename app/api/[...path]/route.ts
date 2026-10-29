import { NextRequest, NextResponse } from 'next/server';
import { envelopeHeaders, notFoundBody } from '@/lib/apiEnvelope';

export const dynamic = 'force-dynamic';

function rid(request: NextRequest) {
  return request.headers.get('x-request-id') || crypto.randomUUID();
}

function unmatched(request: NextRequest) {
  const id = rid(request);
  return NextResponse.json(notFoundBody(id), {
    status: 404,
    headers: envelopeHeaders(id),
  });
}

export async function GET(request: NextRequest) {
  return unmatched(request);
}
export async function HEAD(request: NextRequest) {
  return new NextResponse(null, { status: 404, headers: envelopeHeaders(rid(request)) });
}
export async function POST(request: NextRequest) {
  return unmatched(request);
}
export async function PUT(request: NextRequest) {
  return unmatched(request);
}
export async function PATCH(request: NextRequest) {
  return unmatched(request);
}
export async function DELETE(request: NextRequest) {
  return unmatched(request);
}
