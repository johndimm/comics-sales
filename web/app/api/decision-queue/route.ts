import { NextRequest, NextResponse } from 'next/server';

const UPSTREAM = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

export async function GET(req: NextRequest) {
  const qs = req.nextUrl.searchParams.toString();
  const url = `${UPSTREAM}/api/decision-queue${qs ? `?${qs}` : ''}`;
  try {
    const res = await fetch(url, { cache: 'no-store' });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'content-type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (e: any) {
    return NextResponse.json({ error: 'upstream_unreachable', detail: String(e?.message || e) }, { status: 502 });
  }
}
