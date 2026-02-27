import csv
from pathlib import Path
from urllib.parse import quote_plus


def main():
    src = Path("data/comp_targets_unsold.csv")
    out = Path("data/ebay_queries_unsold.csv")
    if not src.exists():
        raise SystemExit(f"Missing {src}. Run scripts/export_comp_targets.py first.")

    rows = []
    with src.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            title = (row.get("title") or "").strip()
            issue = (row.get("issue") or "").strip()
            if not title:
                continue
            q = f"{title} {issue}"
            sold_url = (
                "https://www.ebay.com/sch/i.html?_nkw="
                + quote_plus(q)
                + "&_sacat=0&LH_Sold=1&LH_Complete=1"
            )
            rows.append(
                {
                    "title": title,
                    "issue": issue,
                    "year": row.get("year", ""),
                    "class": row.get("class", ""),
                    "grade_numeric": row.get("grade_numeric", ""),
                    "ebay_query": q,
                    "ebay_sold_url": sold_url,
                }
            )

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "issue",
                "year",
                "class",
                "grade_numeric",
                "ebay_query",
                "ebay_sold_url",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
