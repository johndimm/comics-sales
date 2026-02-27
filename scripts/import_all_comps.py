import argparse
from pathlib import Path
from fetch_ebay_comps import import_csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="~/Downloads", help="Directory containing comps CSV files")
    ap.add_argument("--glob", default="*.csv", help="Glob pattern to match CSV files")
    ap.add_argument("--clear", action="store_true", help="Clear market_comps and price_suggestions first")
    args = ap.parse_args()

    root = Path(args.dir).expanduser()
    files = sorted(root.glob(args.glob))
    if not files:
        print(f"No files matched: {root}/{args.glob}")
        return

    if args.clear:
        from app.db import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM market_comps")
        conn.execute("DELETE FROM price_suggestions")
        conn.commit()
        conn.close()
        print("Cleared existing comps and suggestions")

    total = 0
    for f in files:
        print(f"\n==> {f}")
        inserted = import_csv(str(f))
        total += inserted

    print(f"\nDone. Imported {total} sold comps from {len(files)} files.")


if __name__ == "__main__":
    main()
