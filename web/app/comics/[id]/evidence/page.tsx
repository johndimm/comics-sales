import Link from 'next/link';
import EvidenceChart from '@/components/EvidenceChart';

function compThumb(e: any): string | null {
  try {
    const p = typeof e?.raw_payload === 'string' ? JSON.parse(e.raw_payload) : null;
    return p?.image?.imageUrl || p?.thumbnailImages?.[0]?.imageUrl || p?.additionalImages?.[0]?.imageUrl || null;
  } catch {
    return null;
  }
}

type Evidence = {
  comic: any;
  sold_evidence: any[];
  active_evidence: any[];
  sold_count: number;
  active_count: number;
  our_images?: string[];
  offer_id?: string | null;
};

async function getEvidence(id: string): Promise<Evidence> {
  const base = process.env.NEXT_PUBLIC_APP_BASE ?? 'http://127.0.0.1:3000';
  const res = await fetch(`${base}/api/comics/${id}/evidence`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed ${res.status}`);
  return res.json();
}

export default async function EvidencePage({ params }: { params: { id: string } }) {
  const data = await getEvidence(params.id);
  const c = data.comic || {};

  return (
    <main className="container">
      <div className="toolbar" style={{ justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0 }}>Evidence: {c.title} #{c.issue}</h1>
        <Link href="/" target="dashboard_tab">← Dashboard</Link>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="toolbar">
          <span><b>Grade:</b> {c.grade_numeric ?? ''}</span>
          <span><b>Applied FMV:</b> {c.market_price != null ? `$${Number(c.market_price).toFixed(2)}` : ''}</span>
          <span><b>Sold rows:</b> {data.sold_count ?? 0}</span>
          <span><b>Active rows:</b> {data.active_count ?? 0}</span>
        </div>
      </div>


      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginBottom: 12 }}>
        <EvidenceChart
          title="Sold curve"
          points={data.sold_evidence || []}
          grade={c.grade_numeric}
          price={c.market_price}
        />
        <EvidenceChart
          title="Active / offer curve"
          points={data.active_evidence || []}
          grade={c.grade_numeric}
          price={c.active_anchor_price}
        />
      </div>

      <div className="card" style={{ marginBottom: 12, overflowX: 'auto' }}>
        <h3 style={{ marginTop: 0 }}>Sold evidence</h3>
        <table className="table">
          <thead>
            <tr><th>#</th><th>Thumb</th><th>Title</th><th>Price</th><th>Ship</th><th>Total</th><th>Date</th><th>Grade</th><th>Company</th><th>Score</th><th>Link</th></tr>
          </thead>
          <tbody>
            {(data.sold_evidence || []).map((e, i) => {
              const total = (Number(e.price || 0) + Number(e.shipping || 0)) || null;
              const thumb = compThumb(e);
              return (
                <tr key={e.comp_id ?? i}>
                  <td>{e.rank ?? i + 1}</td>
                  <td>{thumb ? <a href={thumb} target="_blank" rel="noreferrer"><img src={thumb} alt="thumb" style={{ width: 44, height: 58, objectFit: 'cover', border: '1px solid #e5e7eb', borderRadius: 6 }} /></a> : ''}</td>
                  <td>{e.title}</td>
                  <td>{e.price != null ? `$${Number(e.price).toFixed(2)}` : ''}</td>
                  <td>{e.shipping != null ? `$${Number(e.shipping).toFixed(2)}` : ''}</td>
                  <td>{total != null ? `$${Number(total).toFixed(2)}` : ''}</td>
                  <td>{e.sold_date ?? ''}</td>
                  <td>{e.grade_numeric ?? ''}</td>
                  <td>{e.grade_company ?? ''}</td>
                  <td>{e.match_score != null ? Number(e.match_score).toFixed(2) : ''}</td>
                  <td>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">View listing</a> : ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <h3 style={{ marginTop: 0 }}>Active / offered evidence</h3>
        <table className="table">
          <thead>
            <tr><th>Thumb</th><th>Title</th><th>Ask</th><th>Ship</th><th>Total</th><th>Grade</th><th>Company</th><th>Score</th><th>Link</th></tr>
          </thead>
          <tbody>
            {(data.active_evidence || []).map((e, i) => {
              const total = (Number(e.price || 0) + Number(e.shipping || 0)) || null;
              const thumb = compThumb(e);
              return (
                <tr key={e.comp_id ?? i}>
                  <td>{thumb ? <a href={thumb} target="_blank" rel="noreferrer"><img src={thumb} alt="thumb" style={{ width: 44, height: 58, objectFit: 'cover', border: '1px solid #e5e7eb', borderRadius: 6 }} /></a> : ''}</td>
                  <td>{e.title}</td>
                  <td>{e.price != null ? `$${Number(e.price).toFixed(2)}` : ''}</td>
                  <td>{e.shipping != null ? `$${Number(e.shipping).toFixed(2)}` : ''}</td>
                  <td>{total != null ? `$${Number(total).toFixed(2)}` : ''}</td>
                  <td>{e.grade_numeric ?? ''}</td>
                  <td>{e.grade_company ?? ''}</td>
                  <td>{e.match_score != null ? Number(e.match_score).toFixed(2) : ''}</td>
                  <td>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">View listing</a> : ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
