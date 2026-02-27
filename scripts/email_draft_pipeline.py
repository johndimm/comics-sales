#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "email_pipeline.db"

# Hard safety lock for this rollout.
SEND_ENABLED = False

LOW_RISK_KEYWORDS = [
    "available", "in stock", "still have", "ship", "shipping", "when can", "tracking",
    "condition", "photos", "price", "offer", "best price", "bundle", "combined shipping",
]

RISK_KEYWORDS = [
    "return", "refund", "not as described", "damaged", "broken", "missing",
    "chargeback", "fraud", "scam", "lawyer", "legal", "threat", "paypal dispute",
]

BLOCK_KEYWORDS = [
    "off ebay", "off-platform", "wire transfer", "zelle", "cashapp", "venmo",
    "text me", "whatsapp me", "telegram me",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_himalaya(args: list[str]) -> str:
    cmd = ["himalaya", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"himalaya failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def clean_output(s: str) -> str:
    # Himalaya can print ANSI warning lines before JSON.
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
    lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("WARN")]
    return "\n".join(lines).strip()


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          envelope_id TEXT UNIQUE NOT NULL,
          from_name TEXT,
          from_addr TEXT,
          subject TEXT,
          received_at TEXT,
          body_text TEXT,
          risk_level TEXT NOT NULL,
          risk_reason TEXT,
          status TEXT NOT NULL DEFAULT 'queued',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER NOT NULL,
          tone TEXT NOT NULL,
          draft_text TEXT NOT NULL,
          rationale TEXT,
          status TEXT NOT NULL DEFAULT 'pending_review',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(message_id) REFERENCES email_messages(id)
        )
        """
    )
    conn.commit()


def classify_email(text: str) -> tuple[str, str]:
    t = (text or "").lower()

    for k in BLOCK_KEYWORDS:
        if k in t:
            return ("block", f"contains blocked pattern: '{k}'")

    for k in RISK_KEYWORDS:
        if k in t:
            return ("needs_review", f"contains risk keyword: '{k}'")

    for k in LOW_RISK_KEYWORDS:
        if k in t:
            return ("low_risk", f"contains low-risk keyword: '{k}'")

    return ("needs_review", "no confident low-risk keyword match")


def looks_like_ebay_buyer_mail(from_addr: str | None, subject: str | None, body: str | None) -> bool:
    f = (from_addr or "").lower().strip()
    if any(x in f for x in ["accounts.google.com", "no-reply@google", "mailer-daemon"]):
        return False

    blob = "\n".join([f, (subject or ""), (body or "")]).lower()
    markers = [
        "ebay", "buyer", "offer", "watcher", "item", "listing", "order",
        "tracking", "shipped", "delivered", "return", "refund", "invoice",
    ]
    return any(m in blob for m in markers)


def generate_draft(from_name: str | None, subject: str | None, body: str | None, tone: str = "friendly") -> tuple[str, str]:
    name = (from_name or "there").strip() or "there"
    subj = (subject or "your message").strip()
    body = (body or "").strip()

    if tone == "friendly":
        opener = f"Hi {name},\n\nThanks for reaching out about {subj}."
        closer = "\n\nBest,\nJohn"
    else:
        opener = f"Hello {name},\n\nThank you for your message regarding {subj}."
        closer = "\n\nRegards,\nJohn"

    # Lightweight intent hints (safe placeholder style).
    low = body.lower()
    if "available" in low or "still have" in low:
        middle = "\n\nYes, this item is available."
        rationale = "availability intent detected"
    elif "ship" in low or "shipping" in low:
        middle = "\n\nI can ship promptly with tracking and careful packaging."
        rationale = "shipping intent detected"
    elif "offer" in low or "best price" in low or "price" in low:
        middle = "\n\nThanks for the offer. I can review pricing and get back to you with the best available option."
        rationale = "pricing/offer intent detected"
    else:
        middle = "\n\nI reviewed your note and can help with this. Could you share any extra details needed so I can give you the best answer?"
        rationale = "generic response fallback"

    draft = opener + middle + closer
    return draft, rationale


def fetch_and_queue(limit: int, tone: str) -> dict:
    output = run_himalaya(["envelope", "list", "--page-size", str(limit), "--output", "json"])
    raw = clean_output(output)
    envelopes = json.loads(raw) if raw else []

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    inserted = 0
    skipped = 0
    skipped_non_ebay = 0

    # Oldest first for deterministic queue order.
    for env in reversed(envelopes):
        eid = str(env.get("id", "")).strip()
        if not eid:
            continue

        exists = conn.execute("SELECT id FROM email_messages WHERE envelope_id = ?", (eid,)).fetchone()
        if exists:
            skipped += 1
            continue

        msg_text = run_himalaya(["message", "read", eid, "--output", "json"])
        msg_body = json.loads(clean_output(msg_text)) if msg_text else ""

        from_obj = env.get("from") or {}
        from_name = from_obj.get("name")
        from_addr = from_obj.get("addr")
        subject = env.get("subject")
        received_at = env.get("date")

        if not looks_like_ebay_buyer_mail(from_addr, subject, msg_body):
            skipped_non_ebay += 1
            continue

        risk_level, risk_reason = classify_email(f"{subject}\n{msg_body}")

        ts = now_iso()
        cur = conn.execute(
            """
            INSERT INTO email_messages (
              envelope_id, from_name, from_addr, subject, received_at, body_text,
              risk_level, risk_reason, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (eid, from_name, from_addr, subject, received_at, msg_body, risk_level, risk_reason, ts, ts),
        )
        message_id = cur.lastrowid

        draft_text, rationale = generate_draft(from_name, subject, msg_body, tone=tone)
        conn.execute(
            """
            INSERT INTO drafts (message_id, tone, draft_text, rationale, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending_review', ?, ?)
            """,
            (message_id, tone, draft_text, rationale, ts, ts),
        )
        inserted += 1

    conn.commit()

    stats = conn.execute(
        "SELECT risk_level, COUNT(*) as n FROM email_messages GROUP BY risk_level"
    ).fetchall()
    conn.close()

    return {
        "inserted": inserted,
        "skipped_existing": skipped,
        "skipped_non_ebay": skipped_non_ebay,
        "risk_counts": {r["risk_level"]: r["n"] for r in stats},
        "db": str(DB_PATH),
        "send_enabled": SEND_ENABLED,
    }


def queue_list(status: str | None, limit: int) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    where = ""
    params: list = []
    if status:
        where = "WHERE d.status = ?"
        params.append(status)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT d.id as draft_id, d.status as draft_status, d.tone, d.rationale,
               m.envelope_id, m.from_name, m.from_addr, m.subject, m.received_at,
               m.risk_level, m.risk_reason, d.draft_text
        FROM drafts d
        JOIN email_messages m ON m.id = d.message_id
        {where}
        ORDER BY d.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_approved(draft_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    row = conn.execute("SELECT id, status FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"draft {draft_id} not found"}

    ts = now_iso()
    conn.execute("UPDATE drafts SET status = 'approved', updated_at = ? WHERE id = ?", (ts, draft_id))
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "draft_id": draft_id,
        "status": "approved",
        "send_enabled": SEND_ENABLED,
        "note": "Draft approved for review only. Sending remains disabled by policy lock.",
    }


def cleanup_non_ebay() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    rows = conn.execute(
        "SELECT id, from_addr, subject, body_text FROM email_messages"
    ).fetchall()

    remove_ids = []
    for r in rows:
        if not looks_like_ebay_buyer_mail(r["from_addr"], r["subject"], r["body_text"]):
            remove_ids.append(r["id"])

    deleted = 0
    for mid in remove_ids:
        conn.execute("DELETE FROM drafts WHERE message_id = ?", (mid,))
        conn.execute("DELETE FROM email_messages WHERE id = ?", (mid,))
        deleted += 1

    conn.commit()
    conn.close()
    return {"ok": True, "deleted_messages": deleted}


def main() -> None:
    p = argparse.ArgumentParser(description="Draft-only email pipeline (manual approval, no-send)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_fetch = sub.add_parser("fetch", help="Fetch recent emails and queue drafts")
    s_fetch.add_argument("--limit", type=int, default=25)
    s_fetch.add_argument("--tone", default="friendly", choices=["friendly", "professional"])

    s_queue = sub.add_parser("queue", help="Show draft review queue")
    s_queue.add_argument("--status", default=None, help="pending_review|approved")
    s_queue.add_argument("--limit", type=int, default=20)

    s_approve = sub.add_parser("approve", help="Mark a draft approved (still no-send)")
    s_approve.add_argument("draft_id", type=int)

    sub.add_parser("cleanup-non-ebay", help="Remove queued messages that do not look eBay-related")

    args = p.parse_args()

    if args.cmd == "fetch":
        print(json.dumps(fetch_and_queue(args.limit, args.tone), indent=2))
    elif args.cmd == "queue":
        print(json.dumps(queue_list(args.status, args.limit), indent=2))
    elif args.cmd == "approve":
        print(json.dumps(mark_approved(args.draft_id), indent=2))
    elif args.cmd == "cleanup-non-ebay":
        print(json.dumps(cleanup_non_ebay(), indent=2))


if __name__ == "__main__":
    main()
