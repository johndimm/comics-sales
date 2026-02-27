import Link from 'next/link';

type Evidence = {
  comic: any;
  sold_evidence: any[];
  active_evidence: any[];
  sold_count: number;
  active_count: number;
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
        <Link href="/">← Dashboard</Link>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="toolbar">
          <span><b>Grade:</b> {c.grade_numeric ?? ''}</span>
          <span><b>Applied FMV:</b> {c.market_price != null ? `$${Number(c.market_price).toFixed(2)}` : ''}</span>
          <span><b>Sold rows:</b> {data.sold_count ?? 0}</span>
          <span><b>Active rows:</b> {data.active_count ?? 0}</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12, overflowX: 'auto' }}>
        <h3 style={{ marginTop: 0 }}>Sold evidence</h3>
        <table className="table">
          <thead>
            <tr><th>#</th><th>Title</th><th>Price</th><th>Grade</th><th>Company</th><th>Link</th></tr>
          </thead>
          <tbody>
            {(data.sold_evidence || []).map((e, i) => (
              <tr key={e.comp_id ?? i}>
                <td>{e.rank ?? i + 1}</td>
                <td>{e.title}</td>
                <td>{e.price != null ? `$${Number(e.price).toFixed(2)}` : ''}</td>
                <td>{e.grade_numeric ?? ''}</td>
                <td>{e.grade_company ?? ''}</td>
                <td>{e.url ? <a href={e.url} target="_blank">open</a> : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <h3 style={{ marginTop: 0 }}>Active / offered evidence</h3>
        <table className="table">
          <thead>
            <tr><th>Title</th><th>Ask</th><th>Grade</th><th>Company</th><th>Link</th></tr>
          </thead>
          <tbody>
            {(data.active_evidence || []).map((e, i) => (
              <tr key={e.comp_id ?? i}>
                <td>{e.title}</td>
                <td>{e.price != null ? `$${Number(e.price).toFixed(2)}` : ''}</td>
                <td>{e.grade_numeric ?? ''}</td>
                <td>{e.grade_company ?? ''}</td>
                <td>{e.url ? <a href={e.url} target="_blank">open</a> : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
