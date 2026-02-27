import { NextResponse } from 'next/server';

// Kept for compatibility; draft details/edit now handled by /api/drafts/[offerId]
export async function GET() {
  return NextResponse.json({ ok: true });
}
