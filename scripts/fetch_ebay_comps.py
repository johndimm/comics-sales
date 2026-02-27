"""
Load eBay sold comps.

Modes:
A) CSV import (existing/manual)
   python scripts/fetch_ebay_comps.py --csv path/to/file.csv

B) API fetch + similarity scoring (new)
   python scripts/fetch_ebay_comps.py --api --limit 50 --max-targets 25

Requires in .env for API mode:
  EBAY_CLIENT_ID
  EBAY_CLIENT_SECRET
Optional:
  EBAY_ENV=sandbox|production  (default: sandbox)
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_conn


GRADE_RE = re.compile(r"\b(10\.0|9\.9|9\.8|9\.6|9\.4|9\.2|9\.0|8\.5|8\.0|7\.5|7\.0|6\.5|6\.0|5\.5|5\.0|4\.5|4\.0|3\.5|3\.0|2\.5|2\.0|1\.8|1\.5|1\.0|0\.5)\b")
CGC_RE = re.compile(r"\bCGC\b", re.I)
CBCS_RE = re.compile(r"\bCBCS\b", re.I)
RAW_HINT_RE = re.compile(r"\braw\b|\bungraded\b", re.I)
SIGNED_RE = re.compile(r"\b(signed|signature series|ss)\b", re.I)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
EXCLUDE_TITLE_RE = re.compile(r"\b(reprint|variant|facsimile|toy\s*biz|promo|marvel\s*legends|lot\s*of|set\s*of|blank\s*cover|homage|incentive|ratio\s*variant|marvel\s*team\s*up)\b", re.I)
VOL_RE = re.compile(r"\bvol\.?\s*([0-9]+)\b", re.I)
ANNUAL_RE = re.compile(r"\bannual\b", re.I)

SERIES_ALIASES = {
    "mighty thor": ["mighty thor", "thor", "journey into mystery"],
    "x men": ["x men", "the x men"],
}

SERIES_EXCLUDES = {
    "x men": ["astonishing x men", "uncanny x men", "all new x men", "x men legacy", "ultimate x men", "new x men"],
}


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def query_candidates(target_title: str, target_issue: Optional[str], target_year: Optional[int]):
    title = (target_title or "").strip()
    issue = (target_issue or "").strip()
    year = str(target_year or "").strip()

    base = [f"{title} {issue}".strip()]
    tnorm = normalize(title)

    # Legacy title aliases where market uses older naming.
    if tnorm == "mighty thor":
        base = [
            f"Journey into Mystery {issue} {year}".strip(),
            f"Thor {issue} {year}".strip(),
            f"Mighty Thor {issue} {year}".strip(),
            f"Journey into Mystery {issue}".strip(),
            f"Mighty Thor {issue}".strip(),
        ]
    elif tnorm == "x men":
        base = [
            f"X-Men {issue} {year}".strip(),
            f"The X-Men {issue} {year}".strip(),
            f"X-Men {issue}".strip(),
        ]
    elif year:
        base = [
            f"{title} {issue} {year}".strip(),
            f"{title} {issue}".strip(),
        ]

    out, seen = [], set()
    for q in base:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def strict_title_issue_match(target_title: str, target_issue: Optional[str], target_year: Optional[int], comp_title: str) -> bool:
    tnorm = normalize(target_title)
    cnorm = normalize(comp_title)

    if EXCLUDE_TITLE_RE.search(comp_title or ""):
        return False

    # Avoid cross-product collisions like annuals/volume-era books.
    target_is_annual = bool(ANNUAL_RE.search(target_title or ""))
    comp_is_annual = bool(ANNUAL_RE.search(comp_title or ""))
    if target_is_annual != comp_is_annual:
        return False

    if VOL_RE.search(comp_title or "") and (target_year and target_year < 1985):
        return False

    # Must contain the target series title phrase (allow common shorthand variants).
    title_variants = {tnorm} if tnorm else set()
    if tnorm:
        title_variants.update(SERIES_ALIASES.get(tnorm, []))
        title_variants.add(re.sub(r"\bthe\b", "", tnorm).strip())
        title_variants.add(re.sub(r"\bmighty\b", "", tnorm).strip())
        title_variants = {normalize(v) for v in title_variants if v}

    if title_variants and not any(v in cnorm for v in title_variants):
        return False

    for bad in SERIES_EXCLUDES.get(tnorm, []):
        if normalize(bad) in cnorm:
            return False

    issue = (target_issue or "").strip()
    if issue and issue.isdigit():
        # Require exact issue token like "20" (not "20A", "20B", etc)
        if not re.search(rf"(?<![a-z0-9]){re.escape(issue)}(?![a-z0-9])", cnorm):
            return False
        if re.search(rf"\b{re.escape(issue)}[a-z]\b", cnorm):
            return False

        # Strong guard: the series phrase and issue must appear together as the book identity,
        # not just mention/cameo text elsewhere in the listing title.
        if title_variants:
            matched_pair = False
            for tv in title_variants:
                pair_patterns = [
                    rf"\b{re.escape(tv)}\b(?:\s+\w+){{0,6}}\s*(?:#|no\.?|issue)?\s*{re.escape(issue)}\b",
                    rf"\b(?:#|no\.?|issue)?\s*{re.escape(issue)}\b(?:\s+\w+){{0,6}}\s*\b{re.escape(tv)}\b",
                ]
                if any(re.search(p, cnorm) for p in pair_patterns):
                    matched_pair = True
                    break
            if not matched_pair:
                return False

    # If target is Silver/Bronze era, reject obvious modern-year variants in title.
    if target_year and target_year < 1985:
        years = [int(y) for y in YEAR_RE.findall(comp_title or "")]
        if any(y >= 2000 for y in years):
            return False
        # X-Men is especially collision-prone with many modern volume/variant titles.
        # Require an explicit publication year cue for legacy X-Men issues.
        if tnorm == "x men":
            if not years:
                return False
            if all(y > 1985 for y in years):
                return False

    return True


def ensure_market_comp_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(market_comps)").fetchall()}
    wanted = {
        "grade_company": "TEXT",
        "is_raw": "INTEGER",
        "is_signed": "INTEGER",
        "match_score": "REAL",
    }
    for name, typ in wanted.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE market_comps ADD COLUMN {name} {typ}")
    conn.commit()


def parse_grade_signals(text: str) -> Dict[str, Any]:
    text = text or ""
    m = GRADE_RE.search(text)
    grade_numeric = float(m.group(1)) if m else None

    grade_company = None
    if CGC_RE.search(text):
        grade_company = "CGC"
    elif CBCS_RE.search(text):
        grade_company = "CBCS"

    is_raw = 1 if RAW_HINT_RE.search(text) else 0
    if grade_company:
        is_raw = 0

    is_signed = 1 if SIGNED_RE.search(text) else 0

    return {
        "grade_numeric": grade_numeric,
        "grade_company": grade_company,
        "is_raw": is_raw,
        "is_signed": is_signed,
    }


def similarity_score(target_grade: Optional[float], target_is_slabbed: int, comp: Dict[str, Any]) -> float:
    score = 0.0

    comp_grade = comp.get("grade_numeric")
    if target_grade is not None and comp_grade is not None:
        diff = abs(float(target_grade) - float(comp_grade))
        score += max(0.0, 0.65 - min(diff, 3.0) * 0.2)
    elif target_grade is None and comp_grade is None:
        score += 0.15

    comp_slabbed = 1 if comp.get("grade_company") else 0
    if target_is_slabbed == comp_slabbed:
        score += 0.25
    elif target_is_slabbed and comp.get("is_raw"):
        score -= 0.1

    if comp.get("is_signed"):
        score -= 0.1

    return max(0.0, min(1.0, score))


def import_csv(path: str):
    conn = get_conn()
    ensure_market_comp_columns(conn)
    cur = conn.cursor()
    inserted = 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("title") or row.get("Title")
            issue = row.get("issue") or row.get("Issue") or row.get("number") or row.get("Number")
            price = (
                row.get("Sold Price")
                or row.get("sold_price")
                or row.get("price")
                or row.get("Price")
            )
            sold_date = (
                row.get("Sold Date")
                or row.get("sold_date")
                or row.get("SoldDate")
                or row.get("date")
            )
            url = row.get("url") or row.get("URL") or row.get("community url")

            if not title or price in (None, "", "NFS"):
                continue

            try:
                p = float(str(price).replace("$", "").replace(",", "").strip())
            except ValueError:
                continue

            parsed = parse_grade_signals(f"{title} {row}")

            cur.execute(
                """
                INSERT OR IGNORE INTO market_comps
                (source, listing_type, title, issue, grade_numeric, grade_company, is_raw, is_signed, price, sold_date, url, raw_payload)
                VALUES ('ebay', 'sold', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title.strip(),
                    (issue or "").strip() or None,
                    parsed.get("grade_numeric"),
                    parsed.get("grade_company"),
                    parsed.get("is_raw", 0),
                    parsed.get("is_signed", 0),
                    p,
                    sold_date,
                    url,
                    json.dumps(row),
                ),
            )
            if cur.rowcount:
                inserted += 1

    conn.commit()
    conn.close()
    print(f"Imported {inserted} sold comps from CSV")
    return inserted


def get_oauth_token() -> str:
    load_dotenv()
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    ebay_env = os.getenv("EBAY_ENV", "sandbox").strip().lower() or "sandbox"

    if not client_id or not client_secret:
        raise RuntimeError("Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env")

    oauth_url = (
        "https://api.ebay.com/identity/v1/oauth2/token"
        if ebay_env == "production"
        else "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    )

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }

    resp = requests.post(oauth_url, headers=headers, data=data, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"OAuth failed ({resp.status_code}): {resp.text[:500]}")

    return resp.json()["access_token"]


def api_base() -> str:
    ebay_env = os.getenv("EBAY_ENV", "sandbox").strip().lower() or "sandbox"
    return "https://api.ebay.com" if ebay_env == "production" else "https://api.sandbox.ebay.com"


def fetch_items(token: str, query: str, limit: int = 50, sold_only: bool = True):
    url = f"{api_base()}/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    params = {
        "q": query,
        "limit": max(1, min(200, int(limit))),
    }
    if sold_only:
        params["filter"] = "soldItemsOnly:true"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Browse API failed ({resp.status_code}): {resp.text[:500]}")
    payload = resp.json()
    return payload.get("itemSummaries", [])


def get_targets(max_targets: Optional[int]):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
          id, title, issue, year, grade_numeric,
          CASE WHEN cgc_cert IS NOT NULL AND TRIM(cgc_cert)<>'' THEN 1 ELSE 0 END AS is_slabbed
        FROM comics
        WHERE status IN ('unlisted','drafted')
          AND sold_price IS NULL
        ORDER BY title, issue_sort
        """
    ).fetchall()
    conn.close()
    out = list(rows)
    if max_targets:
        out = out[: max(1, int(max_targets))]
    return out


def upsert_api_comps(limit: int = 50, max_targets: Optional[int] = None, min_score: float = 0.45, include_active: bool = False):
    token = get_oauth_token()
    targets = get_targets(max_targets)

    conn = get_conn()
    ensure_market_comp_columns(conn)
    cur = conn.cursor()

    inserted = 0
    kept = 0

    for t in targets:
        queries = query_candidates(t['title'], t['issue'], t['year'])
        seen_keys = set()

        def store_item(item, listing_type: str, q: str):
            nonlocal kept, inserted
            comp_title = item.get("title") or ""
            if not strict_title_issue_match(t["title"], t["issue"], t["year"], comp_title):
                return

            dedupe_key = (listing_type, (item.get("itemWebUrl") or "").strip() or comp_title.strip().lower())
            if dedupe_key in seen_keys:
                return
            seen_keys.add(dedupe_key)

            parsed = parse_grade_signals(comp_title)
            score = similarity_score(t["grade_numeric"], int(t["is_slabbed"] or 0), parsed)
            if score < min_score:
                return

            price_val = (((item.get("price") or {}).get("value")) or None)
            if price_val is None:
                return

            try:
                price = float(price_val)
            except Exception:
                return

            shipping = 0.0
            shipping_opts = item.get("shippingOptions") or []
            if shipping_opts:
                ship_val = (((shipping_opts[0] or {}).get("shippingCost") or {}).get("value"))
                if ship_val is not None:
                    try:
                        shipping = float(ship_val)
                    except Exception:
                        shipping = 0.0

            sold_date = item.get("itemEndDate") if listing_type == "sold" else None
            if sold_date:
                try:
                    sold_date = datetime.fromisoformat(sold_date.replace("Z", "+00:00")).date().isoformat()
                except Exception:
                    pass

            url = item.get("itemWebUrl")
            raw = dict(item)
            raw["query"] = q
            raw["target_comic_id"] = t["id"]
            raw["target_grade_numeric"] = t["grade_numeric"]
            raw["match_score"] = score

            cur.execute(
                """
                INSERT OR IGNORE INTO market_comps
                (comic_id, source, listing_type, title, issue, grade_numeric, grade_company, is_raw, is_signed,
                 price, shipping, sold_date, url, match_score, raw_payload)
                VALUES (?, 'ebay', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t["id"],
                    listing_type,
                    comp_title,
                    t["issue"],
                    parsed.get("grade_numeric"),
                    parsed.get("grade_company"),
                    parsed.get("is_raw", 0),
                    parsed.get("is_signed", 0),
                    price,
                    shipping,
                    sold_date,
                    url,
                    score,
                    json.dumps(raw),
                ),
            )
            kept += 1
            if cur.rowcount:
                inserted += 1

        for q in queries:
            try:
                sold_items = fetch_items(token, q, limit=limit, sold_only=True)
            except Exception as e:
                print(f"WARN {t['title']} #{t['issue']} query='{q}': {e}")
                continue

            for item in sold_items:
                store_item(item, "sold", q)

            if include_active:
                try:
                    active_items = fetch_items(token, q, limit=limit, sold_only=False)
                except Exception:
                    active_items = []
                for item in active_items:
                    store_item(item, "active", q)

    conn.commit()
    conn.close()
    print(f"Scanned {len(targets)} target comics; kept {kept} comps; inserted {inserted} new rows")
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Path to eBay sold comps CSV export")
    ap.add_argument("--api", action="store_true", help="Fetch sold comps from eBay Browse API")
    ap.add_argument("--include-active", action="store_true", help="Also ingest active listings for anchor-price signal")
    ap.add_argument("--limit", type=int, default=50, help="Results per comic query in API mode")
    ap.add_argument("--max-targets", type=int, default=None, help="Cap number of inventory comics to process")
    ap.add_argument("--min-score", type=float, default=0.45, help="Minimum similarity score to keep a comp")
    args = ap.parse_args()

    if args.csv:
        import_csv(args.csv)
        return

    if args.api:
        upsert_api_comps(limit=args.limit, max_targets=args.max_targets, min_score=args.min_score, include_active=args.include_active)
        return

    print("No mode selected. Use --csv <file> or --api")


if __name__ == "__main__":
    main()
