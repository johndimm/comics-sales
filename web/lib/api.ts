export type DecisionRow = {
  id: number;
  title: string;
  issue: string;
  grade_class?: string;
  grade_numeric?: number | null;
  market_price?: number | null;
  target_price?: number | null;
  action?: string;
  api_offer_id?: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

export async function getDecisionQueue(limit = 200): Promise<DecisionRow[]> {
  const url = `${API_BASE}/api/decision-queue?limit=${limit}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch queue: ${res.status}`);
  return res.json();
}
