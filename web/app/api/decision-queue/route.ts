import { NextRequest, NextResponse } from 'next/server';
import { getDb } from '@/lib/server/db';
import { decisionForRow } from '@/lib/server/pricing';

function gradeClassExpr() {
  return `CASE
    WHEN c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'' THEN 'slabbed'
    WHEN c.community_url IS NOT NULL AND TRIM(c.community_url)<>'' THEN 'raw_community'
    ELSE 'raw_no_community'
  END`;
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams;
  const limit = Math.min(Number(q.get('limit') || 500), 1000);
  const gradeClasses = String(q.get('grade_classes') || 'slabbed,raw_community').split(',').map((x) => x.trim()).filter(Boolean);

  const db = getDb();
  const comicCols = new Set(
    (db.prepare("PRAGMA table_info(comics)").all() as Array<{ name: string }>).map((r) => r.name)
  );
  const hasComicCol = (name: string) => comicCols.has(name);
  const comicColOrNull = (name: string) => (hasComicCol(name) ? `c.${name}` : `NULL AS ${name}`);

  const rows = db
    .prepare(
      `SELECT c.id,c.title,c.issue,c.year,c.marvel_id,c.grade_numeric,c.status,c.qualified_flag,
              ${gradeClassExpr()} AS grade_class,
              ps.market_price,ps.universal_market_price,ps.qualified_market_price,ps.active_anchor_price,
              ps.active_count,ps.confidence,ps.basis_count,
              ${comicColOrNull('thumb_url')}, ${comicColOrNull('importance_text')},
              ${comicColOrNull('api_offer_id')}
       FROM comics c
       LEFT JOIN price_suggestions ps ON ps.comic_id=c.id
       WHERE c.status IN ('unlisted','drafted') AND c.sold_price IS NULL
       ORDER BY c.title, c.issue_sort`
    )
    .all() as any[];

  let out = rows.filter((r) => gradeClasses.includes(String(r.grade_class || '')));
  out = out.map((r) => ({ ...r, ...decisionForRow(r) }));
  out = out.slice(0, limit);

  return NextResponse.json(out);
}
