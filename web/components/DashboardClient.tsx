"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { DecisionRow } from "@/lib/api";

const API_BASE = "";

type Row = DecisionRow & {
  year?: number;
  grade_numeric?: number | null;
  qualified_flag?: number;
  universal_market_price?: number | null;
  qualified_market_price?: number | null;
  market_price?: number | null;
  target_price?: number | null;
  active_anchor_price?: number | null;
  net_raw?: number | null;
  net_slabbed?: number | null;
  slab_lift?: number | null;
  slab_lift_pct?: number | null;
  trend?: string | null;
  trend_pct?: number | null;
  anchor_price?: number | null;
  floor_price?: number | null;
  thumb_url?: string | null;
};

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
  titlePick: string;
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
  rawNoCommunity: true,
  titlePick: "",
};

export default function DashboardClient() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [f, setF] = useState<Filters>(initial);
  const [sortField, setSortField] = useState<string>("market_price");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [modalSrc, setModalSrc] = useState<string>("");

  const exactValueOptions = useMemo(() => {
    if (!f.exactCol) return [] as string[];
    const vals = new Set<string>();
    for (const r of rows as any[]) {
      const v = r?.[f.exactCol];
      if (v == null || v === '') continue;
      vals.add(String(v));
    }
    return Array.from(vals).sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
  }, [rows, f.exactCol]);

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
        setError((data && (data.error || data.detail)) ? `${data.error || "error"}: ${data.detail || ""}` : `HTTP ${res.status}`);
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

  const rowTitles = useMemo(() => {
    // Keep title choices in sync with currently listed rows (apply exact/range filters, ignore titlePick itself).
    let out = [...rows] as any[];

    if (f.exactCol && f.exactVal.trim()) {
      const opts = f.exactVal.toLowerCase().split(',').map((x) => x.trim()).filter(Boolean);
      out = out.filter((r: any) => opts.includes(String(r?.[f.exactCol] ?? '').toLowerCase()));
    }

    if (f.rangeCol && (f.rangeMin || f.rangeMax)) {
      const min = f.rangeMin === '' ? null : Number(f.rangeMin);
      const max = f.rangeMax === '' ? null : Number(f.rangeMax);
      out = out.filter((r: any) => {
        const v = Number(r?.[f.rangeCol]);
        if (Number.isNaN(v)) return false;
        if (min != null && v < min) return false;
        if (max != null && v > max) return false;
        return true;
      });
    }

    const s = new Set<string>();
    for (const r of out) {
      const t = String(r?.title ?? '').trim();
      if (t) s.add(t);
    }
    return Array.from(s).sort((a, b) => a.localeCompare(b));
  }, [rows, f.exactCol, f.exactVal, f.rangeCol, f.rangeMin, f.rangeMax]);

  const [savedSearches, setSavedSearches] = useState<any[]>([]);

  useEffect(() => {
    try {
      setSavedSearches(JSON.parse(localStorage.getItem("savedSearches.v1") || "[]"));
    } catch {
      setSavedSearches([]);
    }
  }, []);

  function saveSearch() {
    const name = window.prompt("Preset name?");
    if (!name) return;
    const items = JSON.parse(localStorage.getItem("savedSearches.v1") || "[]");
    items.push({ name: name.trim(), state: f });
    localStorage.setItem("savedSearches.v1", JSON.stringify(items));
    setSavedSearches(items);
  }

  function runSearch(idx: number) {
    const items = JSON.parse(localStorage.getItem("savedSearches.v1") || "[]");
    const it = items[idx];
    if (!it?.state) return;
    setF(it.state);
  }

  function delSearch(idx: number) {
    const items = JSON.parse(localStorage.getItem("savedSearches.v1") || "[]");
    items.splice(idx, 1);
    localStorage.setItem("savedSearches.v1", JSON.stringify(items));
    setSavedSearches(items);
  }

  function setSort(field: string) {
    if (sortField === field) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  const sortLabel = (field: string, label: string) => {
    const active = sortField === field;
    const arrow = !active ? "⇅" : (sortDir === "asc" ? "▲" : "▼");
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span>{label}</span>
        <span style={{ fontSize: 14, fontWeight: 700, lineHeight: 1 }}>{arrow}</span>
      </span>
    );
  };

  const sortThStyle = (field: string): CSSProperties => ({
    cursor: "pointer",
    userSelect: "none",
    background: sortField === field ? "#eef2ff" : undefined,
    whiteSpace: "nowrap",
  });

  const filtered = useMemo(() => {
    let out = [...rows];
    if (f.titlePick) out = out.filter((r: any) => String(r?.title ?? "") === f.titlePick);
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

    out.sort((a: any, b: any) => {
      const av = a?.[sortField];
      const bv = b?.[sortField];
      const an = Number(av);
      const bn = Number(bv);
      let cmp = 0;
      if (!Number.isNaN(an) && !Number.isNaN(bn) && av != null && bv != null) cmp = an - bn;
      else cmp = String(av ?? "").localeCompare(String(bv ?? ""), undefined, { numeric: true, sensitivity: "base" });
      return sortDir === "asc" ? cmp : -cmp;
    });

    return out;
  }, [rows, f, sortField, sortDir]);

  const money = (v: any) => (v != null && v !== "" ? `$${Number(v).toFixed(2)}` : "");
  const fullImageUrl = (u: string) => {
    if (!u) return u;
    // eBay image URLs often contain size markers like s-l64/s-l300; bump to high-res.
    return u.replace(/s-l\d+/g, "s-l1600");
  };
  const selectionMarketTotal = useMemo(
    () => filtered.reduce((acc: number, r: any) => acc + (Number(r?.market_price || 0) || 0), 0),
    [filtered]
  );

  return (
    <>
      <div className="card" style={{ marginBottom: 12 }}>
        {savedSearches.length ? (
          <div className="toolbar" style={{ marginBottom: 8 }}>
            <span className="muted">Saved searches:</span>
            {savedSearches.map((s: any, i: number) => (
              <span key={`${s.name}-${i}`} className="toolbar" style={{ gap: 4 }}>
                <button onClick={() => runSearch(i)}>{s.name}</button>
                <button onClick={() => delSearch(i)}>x</button>
              </span>
            ))}
          </div>
        ) : null}

        <div className="toolbar" style={{ alignItems: 'end', flexWrap: 'wrap' }}>
          <label>Limit <input type="number" value={f.limit} onChange={(e) => setF({ ...f, limit: Number(e.target.value || 500) })} style={{ width: 90 }} /></label>
          <select value={f.exactCol} onChange={(e) => setF({ ...f, exactCol: e.target.value, exactVal: "" })}>
            <option value="">Exact column</option>
            <option value="title">title</option>
            <option value="issue">issue</option>
            <option value="grade_class">grade_class</option>
            <option value="qualified_flag">qualified_flag</option>
            <option value="action">action</option>
            <option value="trend">trend</option>
          </select>
          <select value={f.exactVal} onChange={(e) => setF({ ...f, exactVal: e.target.value })}>
            <option value="">Exact value (any)</option>
            {exactValueOptions.map((v) => <option key={`exact-${v}`} value={v}>{v}</option>)}
          </select>
          <select value={f.rangeCol} onChange={(e) => setF({ ...f, rangeCol: e.target.value })}>
            <option value="">Range column</option>
            <option value="market_price">market_price</option>
            <option value="target_price">target_price</option>
            <option value="grade_numeric">grade_numeric</option>
            <option value="slab_lift_pct">slab_lift_pct</option>
          </select>
          <input placeholder="min" value={f.rangeMin} onChange={(e) => setF({ ...f, rangeMin: e.target.value })} style={{ width: 90 }} />
          <input placeholder="max" value={f.rangeMax} onChange={(e) => setF({ ...f, rangeMax: e.target.value })} style={{ width: 90 }} />
          <button onClick={load}>Search</button>
          <button onClick={() => setF(initial)}>Clear</button>
          <button onClick={saveSearch}>Save search</button>
        </div>

        <div style={{ marginTop: 10, padding: 10, border: '1px solid #e5e7eb', borderRadius: 10, background: '#f8fafc' }}>
          <div className="muted" style={{ marginBottom: 6 }}>Titles (quick filter)</div>
          <div className="toolbar" style={{ gap: 6 }}>
            <button onClick={() => setF({ ...f, titlePick: "" })} style={{ background: f.titlePick ? "#fff" : "#eef2ff" }}>All</button>
            {rowTitles.map((t) => (
              <button
                key={`title-chip-${t}`}
                onClick={() => setF({ ...f, titlePick: t })}
                style={{ background: f.titlePick === t ? "#eef2ff" : "#fff" }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="muted" style={{ marginBottom: 4 }}>{loading ? "Loading..." : `${filtered.length} rows`}</div>
      <div className="muted" style={{ marginBottom: 8 }}>Selection market value total: ${selectionMarketTotal.toFixed(2)}</div>
      {error ? <div style={{ color: "#b91c1c", marginBottom: 8 }}>API error: {error}</div> : null}
      {modalSrc ? (
        <div onClick={() => setModalSrc("")} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.78)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20, cursor: "zoom-out" }}>
          <img src={modalSrc} alt="full" style={{ maxWidth: "96vw", maxHeight: "92vh", borderRadius: 10, boxShadow: "0 10px 30px rgba(0,0,0,.45)" }} />
        </div>
      ) : null}
      <div className="card" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>Photo</th>
              <th onClick={() => setSort("title")} style={sortThStyle("title")}>{sortLabel("title", "Title")}</th>
              <th onClick={() => setSort("issue")} style={sortThStyle("issue")}>{sortLabel("issue", "Issue")}</th>
              <th>Evidence</th>
              <th>Listing</th>
              <th>Ebay</th>
              <th onClick={() => setSort("grade_class")} style={sortThStyle("grade_class")}>{sortLabel("grade_class", "Class")}</th>
              <th onClick={() => setSort("grade_numeric")} style={sortThStyle("grade_numeric")}>{sortLabel("grade_numeric", "Grade")}</th>
              <th onClick={() => setSort("universal_market_price")} style={sortThStyle("universal_market_price")}>{sortLabel("universal_market_price", "Universal FMV")}</th>
              <th onClick={() => setSort("qualified_market_price")} style={sortThStyle("qualified_market_price")}>{sortLabel("qualified_market_price", "Qualified FMV")}</th>
              <th onClick={() => setSort("market_price")} style={sortThStyle("market_price")}>{sortLabel("market_price", "Market")}</th>
              <th onClick={() => setSort("target_price")} style={sortThStyle("target_price")}>{sortLabel("target_price", "Ask")}</th>
              <th onClick={() => setSort("net_raw")} style={sortThStyle("net_raw")}>{sortLabel("net_raw", "Net Raw")}</th>
              <th onClick={() => setSort("net_slabbed")} style={sortThStyle("net_slabbed")}>{sortLabel("net_slabbed", "Net Slabbed")}</th>
              <th onClick={() => setSort("slab_lift")} style={sortThStyle("slab_lift")}>{sortLabel("slab_lift", "Slab Lift")}</th>
              <th onClick={() => setSort("slab_lift_pct")} style={sortThStyle("slab_lift_pct")}>{sortLabel("slab_lift_pct", "Lift %")}</th>
              <th onClick={() => setSort("trend_pct")} style={sortThStyle("trend_pct")}>{sortLabel("trend_pct", "Trend")}</th>
              <th onClick={() => setSort("anchor_price")} style={sortThStyle("anchor_price")}>{sortLabel("anchor_price", "Anchor")}</th>
              <th onClick={() => setSort("floor_price")} style={sortThStyle("floor_price")}>{sortLabel("floor_price", "Floor")}</th>
              <th>Qualified</th>
              <th onClick={() => setSort("action")} style={sortThStyle("action")}>{sortLabel("action", "Action")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td>{r.thumb_url ? <img src={r.thumb_url} alt="thumb" onClick={() => setModalSrc(fullImageUrl(String(r.thumb_url)))} style={{ width: 44, height: 58, objectFit: "cover", borderRadius: 6, border: "1px solid #e5e7eb", cursor: "zoom-in" }} /> : ""}</td>
                <td><a href={`/comics/${r.id}/evidence`} target="workbench_tab">{r.title}</a></td>
                <td>{r.issue}</td>
                <td><a href={`/comics/${r.id}/evidence`} target="workbench_tab" style={{ display: "inline-block", padding: "4px 10px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff" }}>Evidence</a></td>
                <td><a href={`/comics/${r.id}/listing`} target="workbench_tab" style={{ display: "inline-block", padding: "4px 10px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff" }}>Listing</a></td>
                <td>{r.api_offer_id ? <a href={`/drafts/${r.api_offer_id}`} target="workbench_tab" style={{ display: "inline-block", padding: "4px 10px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff" }}>Draft</a> : ""}</td>
                <td>{r.grade_class ?? ""}</td>
                <td>{r.grade_numeric ?? ""}</td>
                <td>{money(r.universal_market_price)}</td>
                <td>{money(r.qualified_market_price)}</td>
                <td>{money(r.market_price)}</td>
                <td><b>{money(r.target_price)}</b></td>
                <td>{money(r.net_raw)}</td>
                <td>{money(r.net_slabbed)}</td>
                <td>{money(r.slab_lift)}</td>
                <td>{r.slab_lift_pct != null ? `${Number(r.slab_lift_pct).toFixed(1)}%` : ""}</td>
                <td>{r.trend || ""}{r.trend_pct != null ? ` (${Number(r.trend_pct).toFixed(1)}%)` : ""}</td>
                <td>{money(r.anchor_price)}</td>
                <td>{money(r.floor_price)}</td>
                <td>{r.qualified_flag ? "Yes" : ""}</td>
                <td>{r.action || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
