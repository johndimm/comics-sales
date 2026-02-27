from pathlib import Path
from app.db import get_conn


def main():
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    sql = schema_path.read_text()
    conn = get_conn()
    try:
        conn.executescript(sql)
        conn.commit()
        print("Initialized database schema.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
