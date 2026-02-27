import Link from 'next/link';
import DraftEditor from '@/components/DraftEditor';

async function getDraft(offerId: string) {
  const base = process.env.NEXT_PUBLIC_APP_BASE ?? 'http://127.0.0.1:3000';
  const res = await fetch(`${base}/api/drafts/${offerId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed ${res.status}`);
  return res.json();
}

export default async function DraftPage({ params }: { params: { offerId: string } }) {
  const data = await getDraft(params.offerId);
  const offer = data.offer || {};
  const form = data.form || {};

  return (
    <main className="container">
      <div className="toolbar" style={{ justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0 }}>Draft {params.offerId}</h1>
        <div className="toolbar">
          <Link href="/drafts">← Drafts</Link>
          <a href={`http://127.0.0.1:8080/api-drafts/view/${params.offerId}`} target="_blank">legacy view ↗</a>
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
