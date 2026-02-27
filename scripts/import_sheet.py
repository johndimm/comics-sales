import os
import re
import csv
import io
import requests
from dotenv import load_dotenv
from app.db import get_conn

load_dotenv()


def parse_issue_sort(issue_val):
    if issue_val is None:
        return None
    s = str(issue_val).strip()
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else None


def to_float(x):
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    s = s.replace("$", "").replace(",", "").strip()
    if s.upper() in {"NFS", "NA", "N/A", "NONE", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(x):
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def to_boolish(v):
    if v is None:
        return 0
    s = str(v).strip().lower()
    if not s:
        return 0
    return 1 if s in {"1", "true", "yes", "y", "qualified", "q"} else 0


def find_key(row, target):
    target = target.lower().strip()
    for k in row.keys():
        if str(k).lower().strip() == target:
            return k
    return None


def main():
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID missing in .env")

    sheet_gid = os.getenv("GOOGLE_SHEET_GID", "").strip()
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if sheet_gid:
        url += f"&gid={sheet_gid}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    if not rows:
        raise SystemExit("No rows found in sheet export")

    sample = rows[0]
    c_title = find_key(sample, "title")
    c_issue = find_key(sample, "number")
    c_year = find_key(sample, "year")
    c_publisher = find_key(sample, "publisher")
    c_genre = find_key(sample, "genre")
    c_grade = find_key(sample, "grade")
    c_cgc = find_key(sample, "CGC")
    c_artist = find_key(sample, "artist")
    c_notes = find_key(sample, "notes")
    c_mid = find_key(sample, "marvel_id")
    c_comm_url = find_key(sample, "community url")
    c_qualified = find_key(sample, "qualified")
    c_sold_price = find_key(sample, "Sold Price")
    c_sold_date = find_key(sample, "Sold Date")

    if not c_title:
        raise SystemExit(f"Could not find title column. Available: {list(sample.keys())}")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM comics")

    inserted = 0
    for idx, row in enumerate(rows, start=2):
        title = norm(row.get(c_title))
        if not title:
            continue

        issue = norm(row.get(c_issue)) if c_issue else None
        grade_raw = norm(row.get(c_grade)) if c_grade else None
        sold_price = to_float(row.get(c_sold_price)) if c_sold_price else None
        sold_date = norm(row.get(c_sold_date)) if c_sold_date else None
        status = "sold" if sold_price is not None else "unlisted"

        cur.execute(
            """
            INSERT INTO comics (
              source_row, marvel_id, title, issue, issue_sort, year, publisher, genre,
              grade_raw, grade_numeric, cgc_cert, qualified_flag, community_url, artist, notes, status, sold_price, sold_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idx,
                norm(row.get(c_mid)) if c_mid else None,
                title,
                issue,
                parse_issue_sort(issue),
                to_int(row.get(c_year)) if c_year else None,
                norm(row.get(c_publisher)) if c_publisher else None,
                norm(row.get(c_genre)) if c_genre else None,
                grade_raw,
                to_float(grade_raw),
                norm(row.get(c_cgc)) if c_cgc else None,
                to_boolish(row.get(c_qualified)) if c_qualified else 0,
                norm(row.get(c_comm_url)) if c_comm_url else None,
                norm(row.get(c_artist)) if c_artist else None,
                norm(row.get(c_notes)) if c_notes else None,
                status,
                sold_price,
                sold_date,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"Imported {inserted} comics from sheet")


if __name__ == "__main__":
    main()
