import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { getDb } from '@/lib/server/db';
import { decisionForRow } from '@/lib/server/pricing';

function extractThumbFromPayload(raw: unknown): string | null {
  if (!raw || typeof raw !== 'string') return null;
  try {
    const p = JSON.parse(raw) as any;
    return (
      p?.image?.imageUrl ||
      p?.thumbnailImages?.[0]?.imageUrl ||
      p?.additionalImages?.[0]?.imageUrl ||
      null
    );
  } catch {
    return null;
  }
}

function parseIssueNum(issue: unknown): string {
  const s = String(issue ?? '').trim();
  const m = s.match(/\d+/);
  return m ? String(Number(m[0])) : s;
}

function loadOfferIndex(): Map<string, string> {
  const candidates = [
    path.resolve(process.cwd(), '../data/api_offer_ledger.jsonl'),
    path.resolve(process.cwd(), 'data/api_offer_ledger.jsonl'),
  ];
  const p = candidates.find((x) => fs.existsSync(x));
  const out = new Map<string, string>();
  if (!p) return out;

  const lines = fs.readFileSync(p, 'utf-8').split(/\r?\n/).filter(Boolean);
  for (const line of lines) {
    try {
      const r = JSON.parse(line) as any;
      const title = String(r?.title || '').toLowerCase();
      const m = title.match(/^(.*?)\s*#\s*(\d+)/);
      const offerId = r?.offerId;
      if (!m || !offerId) continue;
      const key = `${m[1].trim()}|${String(Number(m[2]))}`;
      out.set(key, String(offerId));
    } catch {}
  }
  return out;
}

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
              ${comicColOrNull('api_offer_id')},
              (
                SELECT mc.raw_payload
                FROM market_comps mc
                WHERE mc.comic_id = c.id AND mc.raw_payload IS NOT NULL AND TRIM(mc.raw_payload) <> ''
                ORDER BY (mc.listing_type='active') DESC, COALESCE(mc.match_score,0) DESC, mc.id DESC
                LIMIT 1
              ) AS thumb_payload
       FROM comics c
       LEFT JOIN price_suggestions ps ON ps.comic_id=c.id
       WHERE c.status IN ('unlisted','drafted') AND c.sold_price IS NULL
       ORDER BY c.title, c.issue_sort`
    )
    .all() as any[];

  const offerIndex = loadOfferIndex();

  let out = rows.filter((r) => gradeClasses.includes(String(r.grade_class || '')));
  out = out.map((r) => {
    const computedThumb = extractThumbFromPayload(r.thumb_payload);
    const { thumb_payload, ...rest } = r;
    const key = `${String(r.title || '').trim().toLowerCase()}|${parseIssueNum(r.issue)}`;
    return {
      ...rest,
      thumb_url: r.thumb_url || computedThumb || null,
      api_offer_id: r.api_offer_id || offerIndex.get(key) || null,
      ...decisionForRow(r),
    };
  });
  out = out.slice(0, limit);

  return NextResponse.json(out);
}
