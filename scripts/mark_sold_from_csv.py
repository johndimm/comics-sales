import csv
import argparse
from app.db import get_conn


def to_float(x):
    if x is None:
        return None
    s = str(x).strip().replace("$", "").replace(",", "")
    if not s or s.upper() in {"NFS", "NA", "N/A", "NONE", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="CSV with Sold Price/Sold Date/title/number/marvel_id")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    updates = 0
    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sold_price = to_float(row.get("Sold Price") or row.get("sold_price"))
            if sold_price is None:
                continue
            sold_date = row.get("Sold Date") or row.get("sold_date") or row.get("date")
            marvel_id = (row.get("marvel_id") or "").strip()
            title = (row.get("title") or "").strip()
            issue = (row.get("number") or row.get("issue") or "").strip()

            if marvel_id and marvel_id != "#N/A":
                cur.execute(
                    "UPDATE comics SET status='sold', sold_price=?, sold_date=? WHERE marvel_id=?",
                    (sold_price, sold_date, marvel_id),
                )
                updates += cur.rowcount
            elif title and issue:
                cur.execute(
                    "UPDATE comics SET status='sold', sold_price=?, sold_date=? WHERE title=? AND issue=?",
                    (sold_price, sold_date, title, issue),
                )
                updates += cur.rowcount

    conn.commit()
    conn.close()
    print(f"Marked {updates} comics as sold from CSV")


if __name__ == "__main__":
    main()
