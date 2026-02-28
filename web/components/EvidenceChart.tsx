"use client";

import { useMemo } from 'react';

type P = { grade_numeric?: number | null; price?: number | null; title?: string; is_raw?: number | boolean; comp_id?: number | string };

function median(vals: number[]) {
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  if (!n) return null;
  const m = Math.floor(n / 2);
  return n % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function seriesFrom(points: Array<{ g: number; p: number }>) {
  const byGrade = new Map<number, number[]>();
  for (const d of points) byGrade.set(d.g, [...(byGrade.get(d.g) || []), d.p]);
  return [...byGrade.entries()]
    .map(([g, vals]) => ({ g, p: median(vals) || 0 }))
    .sort((a, b) => a.g - b.g);
}

function smoothPath(series: Array<{ g: number; p: number }>, sx: (x: number) => number, sy: (y: number) => number) {
  if (series.length < 2) return '';
  const xy = series.map((s) => ({ x: sx(s.g), y: sy(s.p) }));
  let d = `M ${xy[0].x.toFixed(1)} ${xy[0].y.toFixed(1)}`;
  for (let i = 1; i < xy.length; i++) {
    const prev = xy[i - 1];
    const cur = xy[i];
    const cx = (prev.x + cur.x) / 2;
    const cy = (prev.y + cur.y) / 2;
    d += ` Q ${prev.x.toFixed(1)} ${prev.y.toFixed(1)} ${cx.toFixed(1)} ${cy.toFixed(1)}`;
  }
  const last = xy[xy.length - 1];
  d += ` T ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
  return d;
}

function interpPrice(series: Array<{ g: number; p: number }>, g: number) {
  if (!series.length) return null;
  if (series.length === 1) return series[0].p;
  if (g <= series[0].g) return series[0].p;
  if (g >= series[series.length - 1].g) return series[series.length - 1].p;
  for (let i = 0; i < series.length - 1; i++) {
    const lo = series[i];
    const hi = series[i + 1];
    if (lo.g <= g && g <= hi.g) {
      const t = (g - lo.g) / (hi.g - lo.g);
      if (lo.p > 0 && hi.p > 0) {
        return Math.exp(Math.log(lo.p) + t * (Math.log(hi.p) - Math.log(lo.p)));
      }
      return lo.p + t * (hi.p - lo.p);
    }
  }
  return null;
}

export default function EvidenceChart({ points, grade, price, title, tableKey }: { points: P[]; grade?: number | null; price?: number | null; title: string; tableKey?: 'sold' | 'active' }) {
  const w = 560, h = 250, pad = 30;

  const data = useMemo(() => (
    (points || [])
      .filter((p) => p.grade_numeric != null && p.price != null)
      .map((p) => ({ g: Number(p.grade_numeric), p: Number(p.price), raw: !!p.is_raw, t: p.title || '', compId: p.comp_id }))
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

  const rawPts = data.filter((d) => d.raw);
  const slabPts = data.filter((d) => !d.raw);
  const rawSeries = seriesFrom(rawPts);
  const slabSeries = seriesFrom(slabPts);

  const rawPath = smoothPath(rawSeries, sx, sy);
  const slabPath = smoothPath(slabSeries, sx, sy);

  let dotY: number | null = null;
  if (grade != null) {
    const g = Number(grade);
    const slabEst = interpPrice(slabSeries, g);
    const rawEst = interpPrice(rawSeries, g);
    dotY = slabEst ?? rawEst;
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

        {slabPath ? <path d={slabPath} fill="none" stroke="#1d4ed8" strokeWidth="2" opacity="0.95" /> : null}
        {rawPath ? <path d={rawPath} fill="none" stroke="#b91c1c" strokeWidth="2" opacity="0.95" /> : null}

        {data.map((d, i) => (
          <circle
            key={i}
            cx={sx(d.g)}
            cy={sy(d.p)}
            r="4.8"
            fill={d.raw ? '#dc2626' : '#2563eb'}
            style={{ cursor: d.compId != null ? 'pointer' : 'default' }}
            onClick={() => {
              if (tableKey == null || d.compId == null) return;
              const id = `${tableKey}-row-${d.compId}`;
              document.querySelectorAll('tr.comp-highlight').forEach((el) => el.classList.remove('comp-highlight'));
              const row = document.getElementById(id);
              if (row) {
                row.classList.add('comp-highlight');
                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }
            }}
          >
            <title>{`${d.raw ? 'RAW' : 'SLAB/UNSPEC'} • G ${d.g} • $${d.p.toFixed(2)} • ${d.t}`}</title>
          </circle>
        ))}
        {grade != null && dotY != null ? <circle cx={sx(Number(grade))} cy={sy(dotY)} r="5.5" fill="#111" /> : null}
      </svg>
    </div>
  );
}
