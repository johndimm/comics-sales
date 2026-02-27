"use client";

import { useMemo } from 'react';

type P = { grade_numeric?: number | null; price?: number | null; title?: string; is_raw?: number | boolean };

function median(vals: number[]) {
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  if (!n) return null;
  const m = Math.floor(n / 2);
  return n % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export default function EvidenceChart({ points, grade, price, title }: { points: P[]; grade?: number | null; price?: number | null; title: string }) {
  const w = 560, h = 250, pad = 30;

  const data = useMemo(() => (
    (points || [])
      .filter((p) => p.grade_numeric != null && p.price != null)
      .map((p) => ({ g: Number(p.grade_numeric), p: Number(p.price), raw: !!p.is_raw, t: p.title || '' }))
  ), [points]);

  if (!data.length) return <div className="card"><b>{title}</b><div className="muted">No chartable points.</div></div>;

  const xs = data.map((d) => d.g);
  const ys = data.map((d) => d.p);
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (x0 === x1) { x0 -= 0.5; x1 += 0.5; }
  if (y0 === y1) { y0 = 0; y1 += 1; }

  const sx = (x: number) => pad + (x - x0) * ((w - 2 * pad) / (x1 - x0));
  const sy = (y: number) => h - pad - (y - y0) * ((h - 2 * pad) / (y1 - y0));

  const byGrade = new Map<number, number[]>();
  for (const d of data) {
    byGrade.set(d.g, [...(byGrade.get(d.g) || []), d.p]);
  }
  const series = [...byGrade.entries()]
    .map(([g, vals]) => ({ g, p: median(vals) || 0 }))
    .sort((a, b) => a.g - b.g);

  const path = series.map((s, i) => `${i ? 'L' : 'M'} ${sx(s.g).toFixed(1)} ${sy(s.p).toFixed(1)}`).join(' ');

  let dotY: number | null = null;
  if (grade != null) {
    const tg = Number(grade);
    if (series.length === 1) dotY = series[0].p;
    else {
      const lo = [...series].filter((s) => s.g <= tg).pop();
      const hi = series.find((s) => s.g >= tg);
      if (lo && hi) {
        if (hi.g === lo.g) dotY = lo.p;
        else {
          const t = (tg - lo.g) / (hi.g - lo.g);
          dotY = lo.p + t * (hi.p - lo.p);
        }
      }
    }
  }
  if (dotY == null && price != null) dotY = Number(price);

  const start = Math.ceil(y0 / 100) * 100;
  const end = Math.floor(y1 / 100) * 100;

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <b>{title}</b>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="250" style={{ display: 'block', marginTop: 8 }}>
        <rect x="0" y="0" width={w} height={h} fill="#fff" />
        {Array.from({ length: end >= start ? Math.floor((end - start) / 100) + 1 : 0 }).map((_, i) => {
          const gy = start + i * 100;
          const y = sy(gy);
          return (
            <g key={gy}>
              <line x1={pad} y1={y} x2={w - pad} y2={y} stroke="#e5e7eb" />
              <text x={pad + 4} y={y - 2} fontSize="10" fill="#9ca3af">${gy}</text>
            </g>
          );
        })}
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#9ca3af" />
        <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#9ca3af" />
        <path d={path} fill="none" stroke="#1d4ed8" strokeWidth="2" opacity="0.9" />
        {data.map((d, i) => (
          <circle key={i} cx={sx(d.g)} cy={sy(d.p)} r="4.8" fill={d.raw ? '#dc2626' : '#2563eb'}>
            <title>{`${d.raw ? 'RAW' : 'SLAB/UNSPEC'} • G ${d.g} • $${d.p.toFixed(2)} • ${d.t}`}</title>
          </circle>
        ))}
        {grade != null && dotY != null ? <circle cx={sx(Number(grade))} cy={sy(dotY)} r="5.5" fill="#111" /> : null}
      </svg>
    </div>
  );
}
