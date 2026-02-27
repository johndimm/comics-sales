"use client";

import { useEffect, useMemo, useState } from "react";
import type { DecisionRow } from "@/lib/api";

const API_BASE = "";

type Filters = {
  limit: number;
  exactCol: string;
  exactVal: string;
  rangeCol: string;
  rangeMin: string;
  rangeMax: string;
  slabbed: boolean;
  rawCommunity: boolean;
  rawNoCommunity: boolean;
};

const initial: Filters = {
  limit: 500,
  exactCol: "",
  exactVal: "",
  rangeCol: "",
  rangeMin: "",
  rangeMax: "",
  slabbed: true,
  rawCommunity: true,
  rawNoCommunity: false,
};

export default function DashboardClient() {
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [f, setF] = useState<Filters>(initial);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const p = new URLSearchParams();
      p.set("limit", String(f.limit || 500));
      const classes = [
        f.slabbed ? "slabbed" : "",
        f.rawCommunity ? "raw_community" : "",
        f.rawNoCommunity ? "raw_no_community" : "",
      ]
        .filter(Boolean)
        .join(",");
      if (classes) p.set("grade_classes", classes);
      const res = await fetch(`${API_BASE}/api/decision-queue?${p.toString()}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) {
        setError((data && (data.error || data.detail)) ? `${data.error || 'error'}: ${data.detail || ''}` : `HTTP ${res.status}`);
        setRows([]);
      } else {
        setRows(Array.isArray(data) ? data : []);
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.limit, f.slabbed, f.rawCommunity, f.rawNoCommunity]);

  const filtered = useMemo(() => {
    let out = [...rows];
    if (f.exactCol && f.exactVal.trim()) {
      const opts = f.exactVal.toLowerCase().split(",").map((x) => x.trim()).filter(Boolean);
      out = out.filter((r: any) => opts.includes(String(r?.[f.exactCol] ?? "").toLowerCase()));
    }
    if (f.rangeCol && (f.rangeMin || f.rangeMax)) {
      const min = f.rangeMin === "" ? null : Number(f.rangeMin);
      const max = f.rangeMax === "" ? null : Number(f.rangeMax);
      out = out.filter((r: any) => {
        const v = Number(r?.[f.rangeCol]);
        if (Number.isNaN(v)) return false;
        if (min != null && v < min) return false;
        if (max != null && v > max) return false;
        return true;
      });
    }
    return out;
  }, [rows, f]);

  return (
    <>
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="toolbar">
          <label>Limit <input type="number" value={f.limit} onChange={(e) => setF({ ...f, limit: Number(e.target.value || 500) })} style={{ width: 90 }} /></label>
          <label><input type="checkbox" checked={f.slabbed} onChange={(e) => setF({ ...f, slabbed: e.target.checked })} /> slabbed</label>
          <label><input type="checkbox" checked={f.rawCommunity} onChange={(e) => setF({ ...f, rawCommunity: e.target.checked })} /> raw_community</label>
          <label><input type="checkbox" checked={f.rawNoCommunity} onChange={(e) => setF({ ...f, rawNoCommunity: e.target.checked })} /> raw_no_community</label>
          <button onClick={load}>Reload</button>
        </div>
        <div className="toolbar">
          <select value={f.exactCol} onChange={(e) => setF({ ...f, exactCol: e.target.value })}>
            <option value="">Exact column</option>
            <option value="title">title</option>
            <option value="grade_class">grade_class</option>
            <option value="action">action</option>
          </select>
          <input placeholder="Exact value" value={f.exactVal} onChange={(e) => setF({ ...f, exactVal: e.target.value })} />
          <select value={f.rangeCol} onChange={(e) => setF({ ...f, rangeCol: e.target.value })}>
            <option value="">Range column</option>
            <option value="market_price">market_price</option>
            <option value="target_price">target_price</option>
            <option value="grade_numeric">grade_numeric</option>
          </select>
          <input placeholder="min" value={f.rangeMin} onChange={(e) => setF({ ...f, rangeMin: e.target.value })} style={{ width: 90 }} />
          <input placeholder="max" value={f.rangeMax} onChange={(e) => setF({ ...f, rangeMax: e.target.value })} style={{ width: 90 }} />
          <button onClick={() => setF(initial)}>Clear</button>
        </div>
      </div>

      <div className="muted" style={{ marginBottom: 8 }}>{loading ? "Loading..." : `${filtered.length} rows`}</div>
      {error ? <div style={{ color: '#b91c1c', marginBottom: 8 }}>API error: {error}</div> : null}
      <div className="card" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>ID</th><th>Title</th><th>Issue</th><th>Class</th><th>Grade</th><th>Market</th><th>Ask</th><th>Action</th><th>Draft</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.title}</td>
                <td>{r.issue}</td>
                <td>{r.grade_class ?? ""}</td>
                <td>{r.grade_numeric ?? ""}</td>
                <td>{r.market_price != null ? `$${Number(r.market_price).toFixed(2)}` : ""}</td>
                <td><b>{r.target_price != null ? `$${Number(r.target_price).toFixed(2)}` : ""}</b></td>
                <td>{r.action ?? ""}</td>
                <td>{r.api_offer_id ? "yes" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
