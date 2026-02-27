import type { DecisionRow } from '@/lib/api';

export default function DecisionTable({ rows }: { rows: DecisionRow[] }) {
  return (
    <div className="card" style={{ overflowX: 'auto' }}>
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Issue</th>
            <th>Class</th>
            <th>Grade</th>
            <th>Market</th>
            <th>Ask</th>
            <th>Action</th>
            <th>Draft</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td>
              <td>{r.title}</td>
              <td>{r.issue}</td>
              <td>{r.grade_class ?? ''}</td>
              <td>{r.grade_numeric ?? ''}</td>
              <td>{r.market_price != null ? `$${Number(r.market_price).toFixed(2)}` : ''}</td>
              <td><b>{r.target_price != null ? `$${Number(r.target_price).toFixed(2)}` : ''}</b></td>
              <td>{r.action ?? ''}</td>
              <td>{r.api_offer_id ? 'yes' : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
