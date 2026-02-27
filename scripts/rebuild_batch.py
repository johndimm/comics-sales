import argparse, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_conn
from scripts.fetch_ebay_comps import (
    ensure_market_comp_columns,
    get_oauth_token,
    get_targets,
    query_candidates,
    fetch_items,
    strict_title_issue_match,
    parse_grade_signals,
    similarity_score,
)


def run(start: int, count: int, limit: int, min_score: float, include_active: bool):
    targets = get_targets(None)[start:start+count]
    token = get_oauth_token()
    conn = get_conn()
    ensure_market_comp_columns(conn)
    cur = conn.cursor()

    inserted = 0
    kept = 0
    for t in targets:
        seen = set()
        for q in query_candidates(t['title'], t['issue'], t['year']):
            for listing_type, sold_only in [('sold', True), ('active', False)]:
                if listing_type == 'active' and not include_active:
                    continue
                try:
                    items = fetch_items(token, q, limit=limit, sold_only=sold_only)
                except Exception:
                    continue
                for item in items:
                    comp_title = item.get('title') or ''
                    if not strict_title_issue_match(t['title'], t['issue'], t['year'], comp_title):
                        continue
                    dedupe_key = (listing_type, (item.get('itemWebUrl') or '').strip() or comp_title.strip().lower())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    parsed = parse_grade_signals(comp_title)
                    score = similarity_score(t['grade_numeric'], int(t['is_slabbed'] or 0), parsed)
                    if score < min_score:
                        continue
                    price_val = (((item.get('price') or {}).get('value')) or None)
                    if price_val is None:
                        continue
                    try:
                        price = float(price_val)
                    except Exception:
                        continue
                    sold_date = item.get('itemEndDate') if listing_type == 'sold' else None
                    if sold_date:
                        try:
                            sold_date = datetime.fromisoformat(sold_date.replace('Z', '+00:00')).date().isoformat()
                        except Exception:
                            pass
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO market_comps
                        (comic_id, source, listing_type, title, issue, grade_numeric, grade_company, is_raw, is_signed,
                        price, shipping, sold_date, url, match_score, raw_payload)
                        VALUES (?, 'ebay', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            t['id'], listing_type, comp_title, t['issue'], parsed.get('grade_numeric'), parsed.get('grade_company'),
                            parsed.get('is_raw', 0), parsed.get('is_signed', 0), price, 0.0, sold_date,
                            item.get('itemWebUrl'), score, json.dumps(item)
                        ),
                    )
                    kept += 1
                    if cur.rowcount:
                        inserted += 1

    conn.commit()
    conn.close()
    print(f"batch start={start} count={len(targets)} kept={kept} inserted={inserted}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, required=True)
    ap.add_argument('--count', type=int, default=30)
    ap.add_argument('--limit', type=int, default=50)
    ap.add_argument('--min-score', type=float, default=0.25)
    ap.add_argument('--include-active', action='store_true')
    args = ap.parse_args()
    run(args.start, args.count, args.limit, args.min_score, args.include_active)
