export default function HomePage() {
  const legacyUrl = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

  return (
    <main style={{ width: '100vw', height: '100vh', margin: 0, padding: 0, background: '#fff' }}>
      <iframe
        src={legacyUrl}
        title="Comics MVP Legacy"
        style={{ width: '100%', height: '100%', border: 'none' }}
      />
    </main>
  );
}
