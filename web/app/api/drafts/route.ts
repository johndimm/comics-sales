import { NextResponse } from 'next/server';

const UPSTREAM = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

export async function GET() {
  try {
    const res = await fetch(`${UPSTREAM}/api-drafts`, { cache: 'no-store' });
    const html = await res.text();
    return NextResponse.json({ html });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
