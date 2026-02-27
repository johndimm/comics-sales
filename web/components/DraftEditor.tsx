"use client";

import { useState } from 'react';

export default function DraftEditor({ offerId, initial }: { offerId: string; initial: { title?: string; price?: string; description?: string } }) {
  const [title, setTitle] = useState(initial?.title ?? '');
  const [price, setPrice] = useState(initial?.price ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  async function save() {
    setSaving(true);
    setMsg('');
    try {
      const res = await fetch(`/api/drafts/${offerId}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title, price, description }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg(`Save failed: ${data?.error || res.status}`);
      } else {
        setMsg('Saved ✅');
      }
    } catch (e: any) {
      setMsg(`Save failed: ${String(e?.message || e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div style={{ display: 'grid', gap: 10 }}>
        <label>
          <div className="muted">Title</div>
          <input value={title} onChange={(e) => setTitle(e.target.value)} style={{ width: '100%' }} />
        </label>
        <label>
          <div className="muted">Price (USD)</div>
          <input value={price} onChange={(e) => setPrice(e.target.value)} style={{ width: 180 }} />
        </label>
        <label>
          <div className="muted">Description</div>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: '100%', minHeight: 220, border: '1px solid #d1d5db', borderRadius: 8, padding: 8 }} />
        </label>
        <div className="toolbar">
          <button onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save changes'}</button>
          {msg ? <span className="muted">{msg}</span> : null}
        </div>
      </div>
    </div>
  );
}
