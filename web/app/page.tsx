import DashboardClient from '@/components/DashboardClient';

export default function HomePage() {
  return (
    <main className="container">
      <h1 style={{ margin: '0 0 10px 0' }}>Comics MVP (Next.js migration)</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Phase 1: interactive dashboard in React, backed by existing FastAPI endpoints.
      </p>
      <div className="toolbar">
        <a className="card" href="http://127.0.0.1:8080" target="_blank">Open legacy app ↗</a>
      </div>
      <DashboardClient />
    </main>
  );
}
