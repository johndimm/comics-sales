import { NextResponse } from 'next/server';
import { getDb } from '@/lib/server/db';

export async function GET() {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT DISTINCT TRIM(title) AS title
       FROM comics
       WHERE status IN ('unlisted','drafted')
         AND sold_price IS NULL
         AND title IS NOT NULL
         AND TRIM(title) <> ''
       ORDER BY title COLLATE NOCASE ASC`
    )
    .all() as Array<{ title: string }>;
  return NextResponse.json(rows.map((r) => r.title));
}
