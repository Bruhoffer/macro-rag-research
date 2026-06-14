"""Patch topic_summaries and trade_summaries bullets columns.

migrate.py used json.loads which fails on the CSV format; ast.literal_eval works.
This script re-reads the CSVs and updates the existing rows in-place.
"""

import ast
import json
import os
from pathlib import Path

import pandas as pd
import psycopg2

RAW_DATA = Path(__file__).parent.parent.parent.parent / "raw-data"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://macrorag:macrorag@localhost:5433/macrorag"
)


def _parse(s):
    if pd.isna(s) or str(s).strip() in ("", "nan", "null"):
        return None
    text = str(s).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def patch_table(cur, csv_file: Path, table: str, group_col: str):
    df = pd.read_csv(csv_file)
    df = df[df["load_end_dt"].isna()]
    df = df[df["status"] == "ok"]

    updated = 0
    skipped = 0
    for _, r in df.iterrows():
        bullets = _parse(r.get("bullets"))
        label_map = _parse(r.get("label_map"))
        if bullets is None:
            skipped += 1
            continue

        cur.execute(
            f"""UPDATE {table}
                SET bullets = %s::jsonb, label_map = %s::jsonb
                WHERE {group_col} = %s
                  AND window_start::date = %s::date
                  AND window_end::date = %s::date""",
            (
                json.dumps(bullets),
                json.dumps(label_map),
                str(r.get("topic", r.get("group_key", ""))),
                str(r.get("window_start", "")),
                str(r.get("window_end", "")),
            ),
        )
        updated += cur.rowcount

    print(f"  {table}: {updated} rows updated, {skipped} skipped (null bullets)")


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    try:
        print("Patching topic_summaries…")
        patch_table(cur, RAW_DATA / "topic_summaries.csv", "topic_summaries", "topic")

        print("Patching trade_summaries…")
        patch_table(cur, RAW_DATA / "trade_summaries.csv", "trade_summaries", "group_key")

        conn.commit()
        print("Done.")

        # Verify
        cur.execute("SELECT count(*) FROM topic_summaries WHERE bullets IS NOT NULL AND bullets != 'null'::jsonb")
        print(f"  topic_summaries with real bullets: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM trade_summaries WHERE bullets IS NOT NULL AND bullets != 'null'::jsonb")
        print(f"  trade_summaries with real bullets: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
