import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { getDb } from '@/lib/server/db';
import { decisionForRow } from '@/lib/server/pricing';
import { ebayBase, ebayToken } from '@/lib/server/ebay';

function compIsRaw(r: any) {
  const gc = String(r?.grade_company || '').trim().toUpperCase();
  if (gc === 'CGC' || gc === 'CBCS') return 0;
  return Number(r?.is_raw || 0) ? 1 : 0;
}

function extractListingUrl(raw: unknown): string | null {
  if (!raw || typeof raw !== 'string') return null;
  try {
    const p = JSON.parse(raw) as any;
    const direct = p?.itemWebUrl || p?.itemAffiliateWebUrl;
    if (direct) return String(direct);
    const itemId = p?.itemId || p?.legacyItemId || p?.item?.itemId || p?.item?.legacyItemId;
    if (itemId) return `https://www.ebay.com/itm/${encodeURIComponent(String(itemId))}`;
    return null;
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

async function fetchDraftImages(offerId: string | null): Promise<string[]> {
  if (!offerId) return [];
  try {
    const token = await ebayToken();
    const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'Accept-Language': 'en-US' };
    const base = ebayBase();
    const ro = await fetch(`${base}/sell/inventory/v1/offer/${offerId}`, { headers: H, cache: 'no-store' });
    if (!ro.ok) return [];
    const offer = await ro.json();
    const sku = offer?.sku;
    if (!sku) return [];
    const ri = await fetch(`${base}/sell/inventory/v1/inventory_item/${sku}`, { headers: H, cache: 'no-store' });
    if (!ri.ok) return [];
    const inv = await ri.json();
    const urls = Array.isArray(inv?.product?.imageUrls) ? inv.product.imageUrls : [];
    return Array.from(new Set(urls.map((u: any) => String(u)).filter(Boolean)));
  } catch {
    return [];
  }
}

function gradeClassExpr() {
  return `CASE
    WHEN c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'' THEN 'slabbed'
    WHEN c.community_url IS NOT NULL AND TRIM(c.community_url)<>'' THEN 'raw_community'
    ELSE 'raw_no_community'
  END`;
}

export async function GET(_: NextRequest, { params }: { params: { id: string } }) {
  const comicId = Number(params.id);
  if (!comicId) return NextResponse.json({ error: 'invalid_id' }, { status: 400 });

  const db = getDb();
  const comic = db
    .prepare(
      `SELECT c.id,c.title,c.issue,c.marvel_id,c.grade_numeric,c.qualified_flag,
              ${gradeClassExpr()} AS grade_class,
              ps.universal_market_price,ps.qualified_market_price,ps.market_price,ps.active_anchor_price,
              ps.active_count,ps.confidence,ps.basis_count
       FROM comics c
       LEFT JOIN price_suggestions ps ON ps.comic_id=c.id
       WHERE c.id=?`
    )
    .get(comicId) as any;

  if (!comic) return NextResponse.json({ error: 'not_found' }, { status: 404 });

  let sold = db
    .prepare(
      `SELECT pse.rank, mc.id as comp_id, mc.title, mc.issue, mc.price, mc.shipping, mc.sold_date,
              mc.grade_numeric, mc.grade_company, mc.is_raw, mc.is_signed, mc.match_score, mc.url, mc.raw_payload
       FROM price_suggestion_evidence pse
       JOIN market_comps mc ON mc.id = pse.comp_id
       WHERE pse.comic_id=? AND mc.listing_type='sold'
       ORDER BY pse.rank`
    )
    .all(comicId) as any[];

  if (!sold.length) {
    sold = db
      .prepare(
        `SELECT ROW_NUMBER() OVER (ORDER BY COALESCE(mc.match_score,0) DESC, mc.id DESC) as rank,
                mc.id as comp_id, mc.title, mc.issue, mc.price, mc.shipping, mc.sold_date,
                mc.grade_numeric, mc.grade_company, mc.is_raw, mc.is_signed, mc.match_score, mc.url, mc.raw_payload
         FROM market_comps mc
         WHERE mc.comic_id=? AND mc.listing_type='sold'
         ORDER BY COALESCE(mc.match_score,0) DESC, mc.id DESC
         LIMIT 40`
      )
      .all(comicId) as any[];
  }

  const active = db
    .prepare(
      `WITH ranked AS (
         SELECT mc.id as comp_id, mc.title, mc.issue, mc.price, mc.shipping, mc.sold_date,
                mc.grade_numeric, mc.grade_company, mc.is_raw, mc.is_signed, mc.match_score, mc.url, mc.raw_payload,
                ROW_NUMBER() OVER (
                  PARTITION BY LOWER(TRIM(COALESCE(mc.title,''))), ROUND(COALESCE(mc.price,0),2),
                               COALESCE(mc.grade_numeric,-1), LOWER(TRIM(COALESCE(mc.grade_company,''))), COALESCE(mc.is_raw,0)
                  ORDER BY COALESCE(mc.match_score,0) DESC, mc.id DESC
                ) AS rn
         FROM market_comps mc
         WHERE mc.comic_id=? AND mc.listing_type='active'
       )
       SELECT comp_id,title,issue,price,shipping,sold_date,grade_numeric,grade_company,is_raw,is_signed,match_score,url,raw_payload
       FROM ranked WHERE rn=1
       ORDER BY COALESCE(match_score,0) DESC, comp_id DESC
       LIMIT 40`
    )
    .all(comicId) as any[];

  const soldEvidence = sold.map((r) => ({ ...r, is_raw: compIsRaw(r), url: r.url || extractListingUrl(r.raw_payload) }));
  const activeEvidence = active.map((r) => ({ ...r, is_raw: compIsRaw(r), url: r.url || extractListingUrl(r.raw_payload) }));
  const priced = { ...comic, ...decisionForRow(comic) };

  const offerIndex = loadOfferIndex();
  const offerKey = `${String(comic.title || '').trim().toLowerCase()}|${parseIssueNum(comic.issue)}`;
  const offerId = offerIndex.get(offerKey) || null;
  const ourImages = await fetchDraftImages(offerId);

  return NextResponse.json({
    comic: { ...comic, ...priced },
    sold_evidence: soldEvidence,
    active_evidence: activeEvidence,
    sold_count: soldEvidence.length,
    active_count: activeEvidence.length,
    offer_id: offerId,
    our_images: ourImages,
  });
}
