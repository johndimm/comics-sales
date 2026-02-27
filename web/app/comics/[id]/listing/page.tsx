import Link from 'next/link';
import { getDb } from '@/lib/server/db';
import { decisionForRow } from '@/lib/server/pricing';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function gradeClassExpr() {
  return `CASE
    WHEN c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'' THEN 'slabbed'
    WHEN c.community_url IS NOT NULL AND TRIM(c.community_url)<>'' THEN 'raw_community'
    ELSE 'raw_no_community'
  END`;
}

function money(v: any) {
  return v == null ? '' : `$${Number(v).toFixed(2)}`;
}

function extractImages(raw: unknown): string[] {
  if (!raw || typeof raw !== 'string') return [];
  try {
    const p = JSON.parse(raw) as any;
    const urls = [
      p?.image?.imageUrl,
      ...(Array.isArray(p?.thumbnailImages) ? p.thumbnailImages.map((x: any) => x?.imageUrl) : []),
      ...(Array.isArray(p?.additionalImages) ? p.additionalImages.map((x: any) => x?.imageUrl) : []),
    ].filter(Boolean);
    return Array.from(new Set(urls.map((u: any) => String(u))));
  } catch {
    return [];
  }
}

export default async function ListingPage({ params }: { params: { id: string } }) {
  const comicId = Number(params.id);
  const db = getDb();
  const row = db
    .prepare(
      `SELECT c.id,c.title,c.issue,c.year,c.marvel_id,c.community_url,c.cgc_cert,c.grade_numeric,c.qualified_flag,
              ${gradeClassExpr()} AS grade_class,
              ps.market_price,ps.universal_market_price,ps.qualified_market_price,ps.active_anchor_price,
              ps.active_count,ps.confidence,ps.basis_count
       FROM comics c
       LEFT JOIN price_suggestions ps ON ps.comic_id=c.id
       WHERE c.id=?`
    )
    .get(comicId) as any;

  if (!row) {
    return (
      <main className="container">
        <div className="card">Comic not found.</div>
      </main>
    );
  }

  const d = { ...row, ...decisionForRow(row) } as any;

  const compPayloads = db
    .prepare(
      `SELECT raw_payload FROM market_comps
       WHERE comic_id=? AND raw_payload IS NOT NULL AND TRIM(raw_payload)<>''
       ORDER BY (listing_type='active') DESC, COALESCE(match_score,0) DESC, id DESC
       LIMIT 20`
    )
    .all(comicId) as Array<{ raw_payload: string }>;
  const photos = Array.from(new Set(compPayloads.flatMap((r) => extractImages(r.raw_payload)))).slice(0, 24);

  const title = `${d.title || ''} #${d.issue || ''}`.trim();
  const listingTitle = `${title}${d.grade_numeric ? ` ${d.grade_numeric}` : ''}${d.qualified_flag ? ' (Qualified)' : ''}`;

  return (
    <main className="container">
      <div className="toolbar" style={{ justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0 }}>Listing Plan</h1>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <Link href={`/comics/${comicId}/evidence`}>Evidence</Link>
          <Link href="/">Dashboard</Link>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div><b>{title}</b></div>
        <div className="muted" style={{ marginTop: 6 }}>Class: {d.grade_class || 'unknown'} · Grade: {d.grade_numeric ?? 'N/A'}{d.qualified_flag ? ' Qualified' : ''}</div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="toolbar">
          <span><b>Universal FMV:</b> {money(d.universal_market_price)}</span>
          <span><b>Qualified FMV:</b> {money(d.qualified_market_price)}</span>
          <span><b>Applied FMV:</b> {money(d.market_price)}</span>
          <span><b>Anchor:</b> {money(d.anchor_price)}</span>
          <span><b>Target:</b> {money(d.target_price)}</span>
          <span><b>Floor:</b> {money(d.floor_price)}</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Photos</h3>
        {photos.length ? (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {photos.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer">
                <img src={u} alt="photo" style={{ width: 130, height: 170, objectFit: 'cover', borderRadius: 8, border: '1px solid #e5e7eb' }} />
              </a>
            ))}
          </div>
        ) : (
          <div className="muted">No photos found in comp payloads.</div>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Draft listing title</h3>
        <div>{listingTitle}</div>
      </div>
    </main>
  );
}
