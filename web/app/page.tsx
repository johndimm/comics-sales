import DashboardClient from '@/components/DashboardClient';

export default function HomePage() {
  return (
    <main className="container">
      <h1 style={{ margin: '0 0 10px 0' }}>Comics MVP (native Next.js)</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Parity rewrite in progress — native React/Next only.
      </p>
      <DashboardClient />
    </main>
  );
}
