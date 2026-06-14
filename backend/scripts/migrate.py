"""
Load all CSVs from raw-data/ into Postgres.

Run from backend/:
    python scripts/migrate.py

Output shows for each table:
  csv_read   → total rows in the CSV file
  filtered   → after SCD-2 (load_end_dt IS NULL) + status='ok' + dedup
  skipped    → dropped for a domain reason (orphan, missing ID, etc.) — with breakdown
  attempted  → rows passed to INSERT
  inserted   → rows actually added to DB  (count_after - count_before)
  conflicts  → rows silently dropped by ON CONFLICT DO NOTHING  (duplicates)
"""

import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

RAW_DATA = Path(os.environ["RAW_DATA_DIR"])
DB_URL = os.environ["DATABASE_URL_SYNC"]

# ── stats ─────────────────────────────────────────────────────────────────────

@dataclass
class TableStats:
    csv_read:   int = 0
    filtered:   int = 0
    attempted:  int = 0
    inserted:   int = 0
    conflicts:  int = 0
    skipped:    dict = field(default_factory=dict)   # {reason: count}

    def skip(self, reason: str, n: int = 1):
        self.skipped[reason] = self.skipped.get(reason, 0) + n

ALL_STATS: dict[str, TableStats] = {}


def _stat(table: str) -> TableStats:
    if table not in ALL_STATS:
        ALL_STATS[table] = TableStats()
    return ALL_STATS[table]


def print_summary():
    cols = ["table", "csv", "filtered", "skipped", "attempted", "inserted", "conflicts"]
    widths = [28, 8, 8, 8, 9, 9, 9]

    def row_str(vals):
        return "  ".join(str(v).rjust(w) for v, w in zip(vals, widths))

    header = row_str(cols)
    sep    = row_str(["-" * w for w in widths])
    print()
    print("=" * len(header))
    print("MIGRATION SUMMARY")
    print("=" * len(header))
    print(header)
    print(sep)

    for tbl, s in ALL_STATS.items():
        skipped_total = sum(s.skipped.values())
        print(row_str([tbl, s.csv_read, s.filtered, skipped_total, s.attempted, s.inserted, s.conflicts]))
        for reason, cnt in s.skipped.items():
            label = f"  ↳ {reason}"
            print(f"  {label:<40} {cnt:>6}")

    print("=" * len(header))
    print()


# ── helpers ───────────────────────────────────────────────────────────────────

SENTIMENT_MAP = {
    "very bullish": 2,
    "bullish":      1,
    "hawkish":      1,
    "neutral":      0,
    "mixed":        0,
    "dovish":       -1,
    "bearish":      -1,
    "very bearish": -2,
}


def parse_numpy_array(s) -> list:
    """Parse NumPy repr strings like \"['a' 'b']\" into a Python list."""
    if pd.isna(s):
        return []
    s = str(s).strip()
    if s in ("[]", "['']", ""):
        return []
    items = re.findall(r"'([^']*)'", s)
    return [i for i in items if i]


def parse_json(s) -> Any:
    if pd.isna(s) or str(s).strip() in ("", "nan", "null"):
        return None
    text = str(s).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        import ast
        return ast.literal_eval(text)
    except Exception:
        return None


def effective_org(source_org, suggested) -> str | None:
    if pd.notna(source_org) and str(source_org).strip() not in ("", "Others"):
        return str(source_org).strip()
    if pd.notna(suggested) and str(suggested).strip():
        return str(suggested).strip()
    return None


def na_str(v) -> str | None:
    if pd.isna(v) or str(v).strip() in ("", "nan"):
        return None
    return str(v).strip()


def na_int(v) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def na_float(v) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def na_bool(v):
    if pd.isna(v):
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


CHUNK_SIZE    = 1000   # characters per chunk (~250 tokens)
CHUNK_OVERLAP = 200    # overlap between consecutive chunks


def chunk_text(text: str) -> list[str]:
    if not text or len(text) < 50:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    url = DB_URL.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def db_count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def insert_rows(cur, table: str, sql: str, rows: list):
    """Insert rows and record inserted/conflict counts in stats."""
    st = _stat(table)
    st.attempted += len(rows)
    if not rows:
        return
    before = db_count(cur, table)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    after = db_count(cur, table)
    st.inserted  += after - before
    st.conflicts += len(rows) - (after - before)


# ── loaders ───────────────────────────────────────────────────────────────────

def load_reference(cur):
    print("Loading reference tables…", flush=True)

    # source_orgs
    so = pd.read_csv(RAW_DATA / "source_orgs_approved.csv")
    st = _stat("source_orgs")
    st.csv_read = len(so)
    rows = []
    for _, r in so.iterrows():
        key = na_str(r["org_shortform_name"])
        if not key:
            st.skip("missing org_shortform_name")
            continue
        rows.append((key, na_str(r["org_name"]), parse_numpy_array(r["org_aliases"]) or None, na_bool(r["is_active"])))
    st.filtered = len(rows)
    insert_rows(cur, "source_orgs",
        "INSERT INTO source_orgs (org_shortform_name, org_name, org_aliases, is_active) VALUES %s ON CONFLICT DO NOTHING",
        rows)

    # topics
    tp = pd.read_csv(RAW_DATA / "topics_approved.csv")
    st = _stat("topics")
    st.csv_read = len(tp)
    rows = []
    for _, r in tp.iterrows():
        key = na_str(r["topic_name"])
        if not key:
            st.skip("missing topic_name")
            continue
        rows.append((key, na_str(r["description"]), na_bool(r["is_active"])))
    st.filtered = len(rows)
    insert_rows(cur, "topics",
        "INSERT INTO topics (topic_name, description, is_active) VALUES %s ON CONFLICT DO NOTHING",
        rows)

    # geographies
    geo = pd.read_csv(RAW_DATA / "geographies_approved.csv")
    st = _stat("geographies")
    st.csv_read = len(geo)
    rows = []
    for _, r in geo.iterrows():
        key = na_str(r["geography_name"])
        if not key:
            st.skip("missing geography_name")
            continue
        rows.append((key, na_str(r["description"]), na_bool(r["is_active"])))
    st.filtered = len(rows)
    insert_rows(cur, "geographies",
        "INSERT INTO geographies (geography_name, description, is_active) VALUES %s ON CONFLICT DO NOTHING",
        rows)


def load_emails(cur) -> dict:
    """Load emails_parsed. Returns {hash: {file_name, email_subject, email_body, email_sent_dt}}."""
    print("Loading emails…", flush=True)
    df = pd.read_csv(RAW_DATA / "emails_parsed.csv")
    st = _stat("emails")
    st.csv_read = len(df)

    # SCD-2 + status
    df_scd   = df[df["load_end_dt"].isna()].copy()
    df_ok    = df_scd[df_scd["status"] == "ok"].copy()
    st.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(df) - len(df_scd))
    st.skip("status != 'ok'",                             len(df_scd) - len(df_ok))

    # Dedup by email_content_hash — keep the row with the longest body
    df_ok["email_body_length"] = pd.to_numeric(df_ok["email_body_length"], errors="coerce")
    df_ok = df_ok.sort_values("email_body_length", ascending=False)
    before_dedup = len(df_ok)
    df_ok = df_ok.drop_duplicates(subset=["email_content_hash"], keep="first")
    st.skip("duplicate email_content_hash (kept longest body)", before_dedup - len(df_ok))
    st.filtered = len(df_ok)

    rows, lookup = [], {}
    for _, r in df_ok.iterrows():
        h = na_str(r["email_content_hash"])
        if not h:
            st.skip("missing email_content_hash")
            continue
        rows.append((
            h,
            na_str(r["file_name"]),
            na_str(r["email_subject"]),
            na_str(r["email_from"]),
            na_str(r["email_to"]),
            na_str(r["email_sent_dt"]),
            na_str(r["email_body"]),
            na_int(r["email_body_length"]),
        ))
        lookup[h] = {
            "file_name":     na_str(r["file_name"]),
            "email_subject": na_str(r["email_subject"]),
            "email_body":    na_str(r["email_body"]),
            "email_sent_dt": na_str(r["email_sent_dt"]),
        }

    insert_rows(cur, "emails",
        """INSERT INTO emails
           (email_content_hash, file_name, email_subject, email_from, email_to,
            email_sent_dt, email_body, email_body_length)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)
    return lookup


def load_key_points(cur, email_lookup: dict):
    print("Loading key_points_full…", flush=True)
    kp = pd.read_csv(RAW_DATA / "key_points.csv")
    st = _stat("key_points_full")
    st.csv_read = len(kp)

    kp_scd = kp[kp["load_end_dt"].isna()].copy()
    kp_ok  = kp_scd[kp_scd["status"] == "ok"].copy()
    st.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(kp) - len(kp_scd))
    st.skip("status != 'ok'",                             len(kp_scd) - len(kp_ok))
    st.filtered = len(kp_ok)

    en = pd.read_csv(RAW_DATA / "key_points_enrichments.csv")
    en_scd = en[en["load_end_dt"].isna()].copy()
    en_ok  = en_scd[en_scd["status"] == "ok"].copy()
    en_ok  = en_ok.drop_duplicates(subset=["keypoint_id"], keep="last").set_index("keypoint_id")

    rows = []
    for _, r in kp_ok.iterrows():
        kp_id = na_str(r["key_point_id"])
        if not kp_id:
            st.skip("missing key_point_id")
            continue
        h = na_str(r["email_content_hash"])
        if h not in email_lookup:
            st.skip("orphan — email_content_hash not in emails table")
            continue

        e            = en_ok.loc[kp_id] if kp_id in en_ok.index else None
        has_enrich   = e is not None
        if not has_enrich:
            st.skip("no matching enrichment row (loaded without enrichments)")

        topics        = parse_numpy_array(e["topics"])               if has_enrich else []
        sug_topics    = parse_numpy_array(e["suggested_topics"])      if has_enrich else []
        geos          = parse_numpy_array(e["geographies"])           if has_enrich else []
        sug_geos      = parse_numpy_array(e["suggested_geographies"]) if has_enrich else []
        sentiment_str = na_str(e["sentiment"])                        if has_enrich else None
        time_ref      = na_str(e["time_reference"])                   if has_enrich else None
        future_hor    = na_str(e["future_time_horizon"])              if has_enrich else None
        sent_score    = SENTIMENT_MAP.get(sentiment_str) if sentiment_str else None

        src     = na_str(r["source_org"])
        sug_src = na_str(r["suggested_source_org"])
        em      = email_lookup[h]
        rows.append((
            kp_id, h,
            na_str(r["email_sent_dt"]), em["email_subject"], em["file_name"],
            src, sug_src, effective_org(src, sug_src),
            na_str(r["key_point_text"]), na_str(r["key_point_citation"]), na_str(r["key_point_context"]),
            topics or None, sug_topics or None, geos or None, sug_geos or None,
            sentiment_str, sent_score, time_ref, future_hor,
        ))

    insert_rows(cur, "key_points_full",
        """INSERT INTO key_points_full
           (key_point_id, email_content_hash, email_sent_dt, email_subject, file_name,
            source_org, suggested_source_org, effective_source_org,
            key_point_text, key_point_citation, key_point_context,
            topics, suggested_topics, geographies, suggested_geographies,
            sentiment, sentiment_score, time_reference, future_time_horizon)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)


def load_trade_ideas(cur, email_lookup: dict):
    print("Loading trade_ideas_full…", flush=True)
    ti = pd.read_csv(RAW_DATA / "trade_ideas.csv")
    st = _stat("trade_ideas_full")
    st.csv_read = len(ti)

    ti_scd = ti[ti["load_end_dt"].isna()].copy()
    ti_ok  = ti_scd[ti_scd["status"] == "ok"].copy()
    st.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(ti) - len(ti_scd))
    st.skip("status != 'ok'",                             len(ti_scd) - len(ti_ok))
    st.filtered = len(ti_ok)

    en = pd.read_csv(RAW_DATA / "trade_ideas_enrichments.csv")
    en_ok = en[(en["load_end_dt"].isna()) & (en["status"] == "ok")].copy()
    en_ok = en_ok.drop_duplicates(subset=["trade_idea_id"], keep="last").set_index("trade_idea_id")

    rows = []
    for _, r in ti_ok.iterrows():
        ti_id = na_str(r["trade_idea_id"])
        if not ti_id:
            st.skip("missing trade_idea_id")
            continue
        h = na_str(r["email_content_hash"])
        if h not in email_lookup:
            st.skip("orphan — email_content_hash not in emails table")
            continue

        e          = en_ok.loc[ti_id] if ti_id in en_ok.index else None
        has_enrich = e is not None
        if not has_enrich:
            st.skip("no matching enrichment row (loaded without enrichments)")

        geos     = parse_numpy_array(e["geographies"])           if has_enrich else []
        sug_geos = parse_numpy_array(e["suggested_geographies"]) if has_enrich else []
        legs_raw = parse_json(e["legs"])                         if has_enrich else None

        src     = na_str(r["source_org"])
        sug_src = na_str(r["suggested_source_org"])
        em      = email_lookup[h]
        rows.append((
            ti_id, h,
            na_str(r["email_sent_dt"]), em["email_subject"], em["file_name"],
            src, sug_src, effective_org(src, sug_src),
            na_str(r["trade_idea_text"]), na_str(r["trade_idea_citation"]), na_str(r["trade_idea_context"]),
            na_str(e["asset_class"])           if has_enrich else None,
            na_str(e["suggested_asset_class"]) if has_enrich else None,
            na_str(e["time_horizon"])          if has_enrich else None,
            geos or None, sug_geos or None,
            na_str(e["target_price"])          if has_enrich else None,
            na_str(e["stop_price"])            if has_enrich else None,
            na_str(e["trigger_condition"])     if has_enrich else None,
            json.dumps(legs_raw) if legs_raw is not None else None,
        ))

    insert_rows(cur, "trade_ideas_full",
        """INSERT INTO trade_ideas_full
           (trade_idea_id, email_content_hash, email_sent_dt, email_subject, file_name,
            source_org, suggested_source_org, effective_source_org,
            trade_idea_text, trade_idea_citation, trade_idea_context,
            asset_class, suggested_asset_class, time_horizon,
            geographies, suggested_geographies,
            target_price, stop_price, trigger_condition, legs)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)


def load_email_chunks(cur, email_lookup: dict):
    print("Loading email_chunks…", flush=True)
    st = _stat("email_chunks")
    st.csv_read = len(email_lookup)   # one logical "source doc" per email

    # Infer source_org per email from key_points (first non-null effective org)
    kp = pd.read_csv(RAW_DATA / "key_points.csv")
    kp_ok = kp[(kp["load_end_dt"].isna()) & (kp["status"] == "ok")].copy()
    hash_to_org: dict[str, str] = {}
    for _, r in kp_ok.iterrows():
        h = na_str(r["email_content_hash"])
        if h and h not in hash_to_org:
            org = effective_org(na_str(r["source_org"]), na_str(r["suggested_source_org"]))
            if org:
                hash_to_org[h] = org

    rows = []
    skipped_no_body = 0
    for h, em in email_lookup.items():
        body   = em.get("email_body") or ""
        chunks = chunk_text(body)
        if not chunks:
            skipped_no_body += 1
            continue
        src_org = hash_to_org.get(h)
        for i, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{h}:{i}"))
            rows.append((chunk_id, h, i, chunk, na_str(em.get("email_sent_dt")), em.get("email_subject"), src_org))

    if skipped_no_body:
        st.skip("email body empty or too short to chunk", skipped_no_body)
    st.filtered = len(rows)

    insert_rows(cur, "email_chunks",
        """INSERT INTO email_chunks
           (chunk_id, email_content_hash, chunk_index, chunk_text,
            email_sent_dt, email_subject, source_org)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)


def load_disagreements(cur):
    print("Loading disagreements…", flush=True)
    df = pd.read_csv(RAW_DATA / "disagreements.csv")
    st = _stat("disagreements")
    st.csv_read = len(df)

    # All rows have load_end_dt=null in this export; dedup by ID
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["disagreement_id"], keep="last")
    if before_dedup > len(df):
        st.skip("duplicate disagreement_id", before_dedup - len(df))
    st.filtered = len(df)

    rows = []
    for _, r in df.iterrows():
        d_id = na_str(r["disagreement_id"])
        if not d_id:
            st.skip("missing disagreement_id")
            continue
        rows.append((
            d_id, na_str(r["group_key"]), na_str(r["geography"]),
            na_str(r["window_start"]), na_str(r["window_end"]),
            na_str(r["scale"]), na_int(r["n_banks"]), na_int(r["n_keypoints"]),
            na_int(r["sentiment_spread"]),
            json.dumps(parse_json(r["bank_positions"])),
        ))

    insert_rows(cur, "disagreements",
        """INSERT INTO disagreements
           (disagreement_id, group_key, geography, window_start, window_end,
            scale, n_banks, n_keypoints, sentiment_spread, bank_positions)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)

    # Validations
    print("Loading disagreement_validations…", flush=True)
    dv = pd.read_csv(RAW_DATA / "disagreement_validations.csv")
    st2 = _stat("disagreement_validations")
    st2.csv_read = len(dv)

    dv_ok = dv[dv["status"] != "failed"].copy()
    st2.skip("status == 'failed'", len(dv) - len(dv_ok))

    before_dedup = len(dv_ok)
    dv_ok = dv_ok.drop_duplicates(subset=["validation_id"], keep="last")
    if before_dedup > len(dv_ok):
        st2.skip("duplicate validation_id", before_dedup - len(dv_ok))

    loaded_dis_ids = {r[0] for r in rows}
    before_orphan = len(dv_ok)
    dv_ok = dv_ok[dv_ok["disagreement_id"].isin(loaded_dis_ids)]
    st2.skip("orphan — disagreement_id not in disagreements table", before_orphan - len(dv_ok))
    st2.filtered = len(dv_ok)

    dv_rows = []
    for _, r in dv_ok.iterrows():
        v_id = na_str(r["validation_id"])
        if not v_id:
            st2.skip("missing validation_id")
            continue
        dv_rows.append((
            v_id, na_str(r["disagreement_id"]),
            na_str(r["group_key"]), na_str(r["geography"]),
            na_str(r["window_start"]), na_str(r["window_end"]),
            na_str(r["status"]), na_bool(r["is_false_positive"]),
            na_str(r["false_positive_reason"]), na_str(r["resolution_summary"]),
            na_float(r["agent_confidence"]),
            json.dumps(parse_json(r["bank_analysis"])),
        ))

    insert_rows(cur, "disagreement_validations",
        """INSERT INTO disagreement_validations
           (validation_id, disagreement_id, group_key, geography, window_start, window_end,
            status, is_false_positive, false_positive_reason, resolution_summary,
            agent_confidence, bank_analysis)
           VALUES %s ON CONFLICT DO NOTHING""",
        dv_rows)


def load_summaries(cur):
    print("Loading topic_summaries…", flush=True)
    ts = pd.read_csv(RAW_DATA / "topic_summaries.csv")
    st = _stat("topic_summaries")
    st.csv_read = len(ts)

    ts_scd = ts[ts["load_end_dt"].isna()].copy()
    ts_ok  = ts_scd[ts_scd["status"] == "ok"].copy()
    st.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(ts) - len(ts_scd))
    st.skip("status != 'ok'",                             len(ts_scd) - len(ts_ok))
    st.filtered = len(ts_ok)

    rows = []
    for _, r in ts_ok.iterrows():
        rows.append((
            str(uuid.uuid4()), na_str(r["topic"]),
            na_str(r["window_start"]), na_str(r["window_end"]),
            json.dumps(parse_json(r["bullets"])), na_int(r["bullet_count"]),
            parse_numpy_array(r["source_orgs"]) or None, na_int(r["kp_count"]),
            json.dumps(parse_json(r["label_map"])),
        ))

    insert_rows(cur, "topic_summaries",
        """INSERT INTO topic_summaries
           (id, topic, window_start, window_end, bullets, bullet_count,
            source_orgs, kp_count, label_map)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)

    print("Loading trade_summaries…", flush=True)
    trs = pd.read_csv(RAW_DATA / "trade_summaries.csv")
    st2 = _stat("trade_summaries")
    st2.csv_read = len(trs)

    trs_scd = trs[trs["load_end_dt"].isna()].copy()
    trs_ok  = trs_scd[trs_scd["status"] == "ok"].copy()
    st2.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(trs) - len(trs_scd))
    st2.skip("status != 'ok'",                             len(trs_scd) - len(trs_ok))
    st2.filtered = len(trs_ok)

    trs_rows = []
    for _, r in trs_ok.iterrows():
        trs_rows.append((
            str(uuid.uuid4()), na_str(r["group_key"]),
            na_str(r["window_start"]), na_str(r["window_end"]),
            json.dumps(parse_json(r["bullets"])), na_int(r["bullet_count"]),
            parse_numpy_array(r["source_orgs"]) or None, na_int(r["kp_count"]),
            json.dumps(parse_json(r["label_map"])),
        ))

    insert_rows(cur, "trade_summaries",
        """INSERT INTO trade_summaries
           (id, group_key, window_start, window_end, bullets, bullet_count,
            source_orgs, kp_count, label_map)
           VALUES %s ON CONFLICT DO NOTHING""",
        trs_rows)


def load_webinars(cur):
    print("Loading webinars…", flush=True)
    df = pd.read_csv(RAW_DATA / "webinars.csv")
    st = _stat("webinars")
    st.csv_read = len(df)

    df_scd = df[df["load_end_dt"].isna()].copy()
    df_ok  = df_scd[df_scd["status"] == "ok"].copy()
    st.skip("load_end_dt IS NOT NULL (SCD-2 historical)", len(df) - len(df_scd))
    st.skip("status != 'ok'",                             len(df_scd) - len(df_ok))
    st.filtered = len(df_ok)

    rows = []
    for _, r in df_ok.iterrows():
        file_name = na_str(r["file_name"])
        if not file_name:
            st.skip("missing file_name")
            continue
        rows.append((
            str(uuid.uuid4()), file_name, na_str(r["source_bank"]),
            na_bool(r["is_webinar"]), na_str(r["title"]), na_str(r["host_bank"]),
            na_str(r["event_datetime"]), na_str(r["event_timezone"]),
            na_str(r["topic_summary"]),
            json.dumps(parse_json(r["speakers"])),
            na_str(r["url"]), na_str(r["location"]),
            na_str(r["created_datetime"]),
        ))

    insert_rows(cur, "webinars",
        """INSERT INTO webinars
           (webinar_id, file_name, source_bank, is_webinar, title, host_bank,
            event_datetime, event_timezone, topic_summary, speakers, url, location, created_datetime)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Connecting to: {DB_URL[:60]}…")
    conn = get_conn()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        load_reference(cur);           conn.commit()
        email_lookup = load_emails(cur); conn.commit()
        load_key_points(cur, email_lookup); conn.commit()
        load_trade_ideas(cur, email_lookup); conn.commit()
        load_email_chunks(cur, email_lookup); conn.commit()
        load_disagreements(cur);       conn.commit()
        load_summaries(cur);           conn.commit()
        load_webinars(cur);            conn.commit()

        print_summary()

    except Exception as e:
        conn.rollback()
        print(f"\nERROR — rolled back: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
