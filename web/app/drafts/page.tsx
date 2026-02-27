import Link from 'next/link';

type Row = {
  id: number;
  title: string;
  issue: string;
  target_price?: number | null;
  api_offer_id?: string | null;
};

async function getRows(): Promise<Row[]> {
  const base = process.env.NEXT_PUBLIC_APP_BASE ?? 'http://127.0.0.1:3000';
  const res = await fetch(`${base}/api/decision-queue?limit=1000`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed ${res.status}`);
  const data = await res.json();
  return (Array.isArray(data) ? data : []).filter((r) => r.api_offer_id);
}

export default async function DraftsPage() {
  const rows = await getRows();
  return (
    <main className="container">
      <div className="toolbar" style={{ justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0 }}>Drafts (migration view)</h1>
        <Link href="/">← Dashboard</Link>
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Comic</th>
              <th>Issue</th>
              <th>Suggested Ask</th>
              <th>Offer ID</th>
              <th>Open</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.id}-${r.api_offer_id}`}>
                <td>{r.title}</td>
                <td>{r.issue}</td>
                <td>{r.target_price != null ? `$${Number(r.target_price).toFixed(2)}` : ''}</td>
                <td>{r.api_offer_id}</td>
                <td><Link href={`/drafts/${r.api_offer_id}`}>view/edit</Link></td>
                <td><a href={`http://127.0.0.1:8080/api-drafts/edit/${r.api_offer_id}`} target="_blank">legacy edit ↗</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
