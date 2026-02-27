# Comics Sales MVP

MVP for managing a high-value comic collection:
- Import inventory from Google Sheets
- Store inventory in SQLite (easy local start)
- Track sold/offer comps (schema ready)
- Generate suggested pricing bands
- Minimal FastAPI service + HTML dashboard

## 1) Setup

```bash
cd comics-mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Configure

Copy env template:

```bash
cp .env.example .env
```

Update `GOOGLE_SHEET_ID` (already prefilled with your sheet).

## 3) Initialize DB + import inventory

```bash
python scripts/init_db.py
python scripts/import_sheet.py
python scripts/price_suggestions.py
```

## 4) Run app

```bash
uvicorn app.main:app --reload --port 8080
```

Open:
- Dashboard: http://localhost:8080/
- JSON API: http://localhost:8080/api/comics?limit=50

## eBay comps

There is a starter module at `scripts/fetch_ebay_comps.py`.
It supports two modes:
1. **Manual CSV import** (recommended to start)
2. **API mode scaffold** (requires your eBay credentials)

### Verify eBay credentials (quick test)

After filling `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` in `.env`, run:

```bash
python scripts/test_ebay_auth.py
```

By default it uses Sandbox (`EBAY_ENV=sandbox`).
Set `EBAY_ENV=production` when you switch to live credentials.

### Pull similar-grade sold comps from eBay API

```bash
python scripts/fetch_ebay_comps.py --api --limit 50 --max-targets 25 --min-score 0.45
python scripts/price_suggestions.py
```

What this does:
- searches sold listings per comic
- parses grade/slab signals from listing titles (e.g., CGC/CBCS/9.8/raw/signed)
- scores comp similarity vs your comic (grade distance + slab/raw parity)
- stores matched comps in `market_comps` (including URL links)
- recomputes suggested prices from matched comps
- saves FMV evidence mapping in `price_suggestion_evidence`

Evidence API:
- `GET /api/comics/{comic_id}/evidence` returns the exact comp rows + links used in FMV

## Draft-Only Email Pipeline (manual approval, no send)

A safe inbox pipeline is available at `scripts/email_draft_pipeline.py`.

What it does now:
- Pulls recent Gmail messages through Himalaya
- Classifies each email (`low_risk`, `needs_review`, `block`)
- Generates a reply draft in your selected tone
- Queues drafts for human review
- Supports `approve` status while keeping send hard-disabled

What it does **not** do:
- It does not send any email (`SEND_ENABLED = False` safety lock)

Run it:

```bash
cd comics-mvp
source .venv/bin/activate
python scripts/email_draft_pipeline.py fetch --limit 25 --tone friendly
python scripts/email_draft_pipeline.py queue --status pending_review --limit 20
python scripts/email_draft_pipeline.py approve 1
python scripts/email_draft_pipeline.py cleanup-non-ebay
```

Data is stored in: `data/email_pipeline.db`

## Notes

- This is intentionally local-first and simple.
- Next step: add authenticated posting workflows for eBay/Shortboxed and cross-post locking.
