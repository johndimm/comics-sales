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

      <DraftEditor offerId={params.offerId} initial={form} />
    </main>
  );
}
