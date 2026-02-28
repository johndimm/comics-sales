import Link from 'next/link';
import DraftEditor from '@/components/DraftEditor';

async function getDraft(offerId: string) {
  const base = process.env.NEXT_PUBLIC_APP_BASE ?? 'http://127.0.0.1:3000';
  const res = await fetch(`${base}/api/drafts/${offerId}`, { cache: 'no-store' });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export default async function DraftPage({ params }: { params: { offerId: string } }) {
  const result = await getDraft(params.offerId);
  if (!result.ok) {
    return (
      <main className="container">
        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <h1 style={{ margin: 0 }}>Draft {params.offerId}</h1>
          <Link href="/drafts">← Drafts</Link>
        </div>
        <div className="card" style={{ color: '#991b1b' }}>
          Failed to load draft ({result.status}). {String(result.data?.error || 'Unknown error')}
        </div>
      </main>
    );
  }
  const data = result.data;
  const offer = data.offer || {};
  const form = data.form || {};
  const images: string[] = Array.isArray(data.images) ? data.images : [];

  return (
    <main className="container">
      <div className="toolbar" style={{ justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0 }}>Draft {params.offerId}</h1>
        <div className="toolbar">
          <Link href="/drafts">← Drafts</Link>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="toolbar">
          <span><b>SKU:</b> {offer.sku || ''}</span>
          <span><b>Status:</b> {offer.status || ''}</span>
          <span><b>Price:</b> {(((offer.pricingSummary || {}).price || {}).value) ? `$${((offer.pricingSummary || {}).price || {}).value}` : ''}</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Photos</h3>
        {images.length ? (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {images.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer">
                <img src={u} alt="draft" style={{ width: 130, height: 170, objectFit: 'cover', borderRadius: 8, border: '1px solid #e5e7eb' }} />
              </a>
            ))}
          </div>
        ) : (
          <div className="muted">No photos on this draft.</div>
        )}
      </div>

      <DraftEditor offerId={params.offerId} initial={form} />
    </main>
  );
}
