from statistics import median
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_conn


def confidence_from_count(n):
    if n >= 8:
        return "high"
    if n >= 3:
        return "medium"
    return "low"


def ensure_tables(cur):
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS price_suggestion_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          comic_id INTEGER NOT NULL,
          comp_id INTEGER NOT NULL,
          rank INTEGER,
          used_in_fmv INTEGER DEFAULT 1,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(comic_id) REFERENCES comics(id) ON DELETE CASCADE,
          FOREIGN KEY(comp_id) REFERENCES market_comps(id) ON DELETE CASCADE,
          UNIQUE(comic_id, comp_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pse_comic ON price_suggestion_evidence(comic_id, rank);
        """
    )

    cols = {r[1] for r in cur.execute("PRAGMA table_info(price_suggestions)").fetchall()}
    if "universal_market_price" not in cols:
        cur.execute("ALTER TABLE price_suggestions ADD COLUMN universal_market_price REAL")
    if "qualified_market_price" not in cols:
        cur.execute("ALTER TABLE price_suggestions ADD COLUMN qualified_market_price REAL")
    if "active_anchor_price" not in cols:
        cur.execute("ALTER TABLE price_suggestions ADD COLUMN active_anchor_price REAL")
    if "active_count" not in cols:
        cur.execute("ALTER TABLE price_suggestions ADD COLUMN active_count INTEGER")


def _norm_title(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def dedupe_comp_rows(rows):
    out = []
    seen = set()
    for r in rows:
        key = (_norm_title(r["title"] if "title" in r.keys() else None), round(float(r["price"] or 0), 2), r["sold_date"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def median_val(vals):
    if not vals:
        return None
    s = sorted(float(v) for v in vals)
    n = len(s)
    m = n // 2
    if n % 2 == 1:
        return s[m]
    return (s[m - 1] + s[m]) / 2.0


def grade_trend_price(rows, target_grade, is_slabbed_book=False):
    use_rows = rows
    if is_slabbed_book:
        certified = [r for r in rows if (r["grade_company"] or "").strip().upper() in {"CGC", "CBCS"}]
        if len(certified) >= 3:
            use_rows = certified

    pts = [(float(r["grade_numeric"]), float(r["price"])) for r in use_rows if r["grade_numeric"] is not None and r["price"] is not None and float(r["price"]) > 0]
    if target_grade is None or len(pts) < 2:
        return None

    tg = float(target_grade)

    # Always use local non-linear weighting so distant grades/outliers don't dominate.
    # This respects "use all grades" while prioritizing comps nearest the target grade.
    local = [p for p in pts if abs(p[0] - tg) <= 1.5]
    if len(local) >= 3:
        pts = local

    if tg >= 9.0:
        bw = 0.22
    elif tg >= 8.0:
        bw = 0.35
    else:
        bw = 0.60

    wsum = 0.0
    lsum = 0.0
    for g, p in pts:
        w = math.exp(-abs(g - tg) / bw)
        wsum += w
        lsum += w * math.log(p)
    if wsum <= 0:
        return None
    return math.exp(lsum / wsum)


def main():
    conn = get_conn()
    cur = conn.cursor()
    ensure_tables(cur)

    comics = cur.execute("SELECT id, title, issue, qualified_flag, grade_numeric, cgc_cert FROM comics").fetchall()
    upserts = 0

    for c in comics:
        rows = cur.execute(
            """
            SELECT id, title, price, sold_date, grade_numeric, match_score, grade_company, is_raw FROM market_comps
            WHERE comic_id = ?
              AND listing_type = 'sold'
              AND price IS NOT NULL
            ORDER BY COALESCE(match_score, 0) DESC, sold_date DESC
            LIMIT 160
            """,
            (c["id"],),
        ).fetchall()
        rows = dedupe_comp_rows(rows)

        is_slabbed_book = bool((c["cgc_cert"] or "").strip())
        tgt_grade = c["grade_numeric"]

        # Keep all sold evidence rows (deduped), any grade.
        prices = [r["price"] for r in rows if r["price"] and r["price"] > 0]
        if not prices:
            cur.execute("DELETE FROM price_suggestion_evidence WHERE comic_id = ?", (c["id"],))
            cur.execute("DELETE FROM price_suggestions WHERE comic_id = ?", (c["id"],))
            continue

        active_rows = cur.execute(
            """
            SELECT price FROM market_comps
            WHERE comic_id = ?
              AND listing_type = 'active'
              AND price IS NOT NULL
            ORDER BY COALESCE(match_score, 0) DESC
            LIMIT 20
            """,
            (c["id"],),
        ).fetchall()
        active_prices = [r["price"] for r in active_rows if r["price"] and r["price"] > 0]

        # Primary FMV: trend-line estimate at target grade (not average/median).
        trend_at_grade = grade_trend_price(rows, tgt_grade, is_slabbed_book=is_slabbed_book)
        if trend_at_grade is not None:
            # Price this book slightly above the fitted line.
            universal_market = round(trend_at_grade * 1.05, 2)
        else:
            # Fallback only when a trend line can't be computed.
            universal_market = round(float(median(prices)), 2)

        # High-grade guardrail: if a very close higher-grade sale exists, keep this
        # valuation reasonably close to it (non-linear premium behavior near top grades).
        if tgt_grade is not None and float(tgt_grade) >= 9.0:
            higher = [float(r["price"]) for r in rows if r["grade_numeric"] is not None and float(r["grade_numeric"]) >= float(tgt_grade) + 0.1 and float(r["grade_numeric"]) <= float(tgt_grade) + 0.4 and float(r["price"]) > 0]
            if higher:
                universal_market = round(max(universal_market, max(higher) * 0.80), 2)

        # Slabbed guardrail: keep slab valuation anchored to nearby slab sales.
        if is_slabbed_book and tgt_grade is not None:
            slab_vals = {}
            for r in rows:
                if float(r["price"]) <= 0:
                    continue
                if (r["grade_company"] or "").strip().upper() not in {"CGC", "CBCS"}:
                    continue
                if r["grade_numeric"] is None:
                    continue
                g = float(r["grade_numeric"])
                slab_vals.setdefault(g, []).append(float(r["price"]))

            slab_pts = []
            for g, vals in slab_vals.items():
                # User preference: for slabbed grade buckets, anchor to best realized sale
                # at that grade (not median), then interpolate across grades.
                top = max(float(v) for v in vals)
                slab_pts.append((g, top))
            slab_pts.sort(key=lambda t: t[0])

            # If we have certified comps immediately below and above target grade,
            # enforce interpolation between them (no pegging to lower bucket).
            below = [p for p in slab_pts if p[0] <= float(tgt_grade)]
            above = [p for p in slab_pts if p[0] >= float(tgt_grade)]
            if below and above:
                gb, pb = max(below, key=lambda t: t[0])
                ga, pa = min(above, key=lambda t: t[0])
                if ga > gb:
                    t = (float(tgt_grade) - gb) / (ga - gb)
                    interp = pb + t * (pa - pb)
                    universal_market = round(max(universal_market, interp), 2)

            # Fallback anchor: nearby certified median within ±0.5
            slab_near = [p for g, p in slab_pts if abs(g - float(tgt_grade)) <= 0.5]
            if len(slab_near) >= 2:
                slab_med = median_val(slab_near)
                universal_market = round(max(universal_market, slab_med), 2)

            # Also do not price a slab below comparable raw sales at same grade band.
            raw_near = [
                float(r["price"]) for r in rows
                if float(r["price"]) > 0
                and (r["grade_company"] or "").strip() == ""
                and r["grade_numeric"] is not None
                and abs(float(r["grade_numeric"]) - float(tgt_grade)) <= 0.5
            ]
            if raw_near:
                universal_market = round(max(universal_market, max(raw_near) * 1.05), 2)

        qualified_market = round(universal_market * 0.6, 2)

        qual_mult = 0.6 if c["qualified_flag"] else 1.0
        quick = round(universal_market * 0.9 * qual_mult, 2)
        market = round(universal_market * qual_mult, 2)
        premium = round(universal_market * 1.15 * qual_mult, 2)
        conf = confidence_from_count(len(prices))

        active_anchor_price = None
        if active_prices:
            active_anchor_price = round(float(median(active_prices)), 2)

        cur.execute(
            """
            INSERT INTO price_suggestions (
              comic_id, quick_sale, market_price, premium_price,
              universal_market_price, qualified_market_price,
              active_anchor_price, active_count,
              confidence, basis_count, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(comic_id) DO UPDATE SET
              quick_sale=excluded.quick_sale,
              market_price=excluded.market_price,
              premium_price=excluded.premium_price,
              universal_market_price=excluded.universal_market_price,
              qualified_market_price=excluded.qualified_market_price,
              active_anchor_price=excluded.active_anchor_price,
              active_count=excluded.active_count,
              confidence=excluded.confidence,
              basis_count=excluded.basis_count,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                c["id"],
                quick,
                market,
                premium,
                universal_market,
                qualified_market,
                active_anchor_price,
                len(active_prices),
                conf,
                len(prices),
            ),
        )

        cur.execute("DELETE FROM price_suggestion_evidence WHERE comic_id = ?", (c["id"],))
        for idx, r in enumerate(rows, start=1):
            cur.execute(
                """
                INSERT OR IGNORE INTO price_suggestion_evidence (comic_id, comp_id, rank, used_in_fmv)
                VALUES (?, ?, ?, 1)
                """,
                (c["id"], r["id"], idx),
            )

        upserts += 1

    conn.commit()
    conn.close()
    print(f"Updated {upserts} price suggestion rows + FMV evidence links")


if __name__ == "__main__":
    main()
