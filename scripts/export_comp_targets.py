import csv
from pathlib import Path
from app.db import get_conn


def main():
    out = Path("data/comp_targets_unsold.csv")
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.title, c.issue, c.year,
               CASE
                 WHEN c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'' THEN 'slabbed'
                 ELSE 'raw_community'
               END AS class,
               c.grade_numeric,
               c.community_url
        FROM comics c
        LEFT JOIN price_suggestions ps ON ps.comic_id = c.id
        WHERE c.status IN ('unlisted','drafted')
          AND c.sold_price IS NULL
          AND (
            (c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'')
            OR ((c.cgc_cert IS NULL OR TRIM(c.cgc_cert)='') AND c.community_url IS NOT NULL AND TRIM(c.community_url)<>'')
          )
          AND ps.comic_id IS NULL
        ORDER BY class, c.title, c.issue_sort
        """
    ).fetchall()
    conn.close()

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "issue", "year", "class", "grade_numeric", "community_url"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], r[3], r[4], r[5]])

    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
