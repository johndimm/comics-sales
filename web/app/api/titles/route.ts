import { NextResponse } from 'next/server';

const UPSTREAM = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

export async function GET() {
  try {
    const res = await fetch(`${UPSTREAM}/api/titles`, { cache: 'no-store' });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'content-type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
