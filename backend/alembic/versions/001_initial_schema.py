"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension (already created manually, but idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Reference tables ────────────────────────────────────────────────────
    op.create_table(
        "source_orgs",
        sa.Column("org_shortform_name", sa.String, primary_key=True),
        sa.Column("org_name",           sa.String),
        sa.Column("org_aliases",        ARRAY(sa.String)),
        sa.Column("is_active",          sa.Boolean, default=True),
    )

    op.create_table(
        "topics",
        sa.Column("topic_name",  sa.String, primary_key=True),
        sa.Column("description", sa.String),
        sa.Column("is_active",   sa.Boolean, default=True),
    )

    op.create_table(
        "geographies",
        sa.Column("geography_name", sa.String, primary_key=True),
        sa.Column("description",    sa.String),
        sa.Column("is_active",      sa.Boolean, default=True),
    )

    # ── Emails ──────────────────────────────────────────────────────────────
    op.create_table(
        "emails",
        sa.Column("email_content_hash", sa.String,                  primary_key=True),
        sa.Column("file_name",          sa.String,                  nullable=False),
        sa.Column("email_subject",      sa.String),
        sa.Column("email_from",         sa.String),
        sa.Column("email_to",           sa.String),
        sa.Column("email_sent_dt",      sa.DateTime(timezone=True)),
        sa.Column("email_body",         sa.Text),
        sa.Column("email_body_length",  sa.Integer),
    )
    op.create_index("ix_email_sent_dt", "emails", ["email_sent_dt"])

    # ── Key points (denormalised) ────────────────────────────────────────────
    op.create_table(
        "key_points_full",
        sa.Column("key_point_id",          sa.String,                  primary_key=True),
        sa.Column("email_content_hash",    sa.String,                  sa.ForeignKey("emails.email_content_hash"), nullable=False),
        sa.Column("email_sent_dt",         sa.DateTime(timezone=True)),
        sa.Column("email_subject",         sa.String),
        sa.Column("file_name",             sa.String),
        sa.Column("source_org",            sa.String),
        sa.Column("suggested_source_org",  sa.String),
        sa.Column("effective_source_org",  sa.String),
        sa.Column("key_point_text",        sa.Text,                    nullable=False),
        sa.Column("key_point_citation",    sa.Text),
        sa.Column("key_point_context",     sa.Text),
        sa.Column("topics",                ARRAY(sa.String)),
        sa.Column("suggested_topics",      ARRAY(sa.String)),
        sa.Column("geographies",           ARRAY(sa.String)),
        sa.Column("suggested_geographies", ARRAY(sa.String)),
        sa.Column("sentiment",             sa.String),
        sa.Column("sentiment_score",       sa.SmallInteger),
        sa.Column("time_reference",        sa.String),
        sa.Column("future_time_horizon",   sa.String),
        sa.Column("kp_embedding",          sa.String),   # placeholder — replaced by vector type below
        sa.Column("kp_fts",                TSVECTOR),
    )
    # Replace placeholder with actual vector column
    op.execute("ALTER TABLE key_points_full DROP COLUMN kp_embedding")
    op.execute("ALTER TABLE key_points_full ADD COLUMN kp_embedding vector(1536)")

    op.create_index("ix_kp_source_org_dt", "key_points_full", ["source_org", "email_sent_dt"])
    op.create_index("ix_kp_sentiment_dt",  "key_points_full", ["sentiment_score", "email_sent_dt"])
    op.create_index("ix_kp_time_ref",      "key_points_full", ["time_reference"])
    op.create_index("ix_kp_sent_dt",       "key_points_full", ["email_sent_dt"])
    op.create_index("ix_kp_topics",        "key_points_full", ["topics"],      postgresql_using="gin")
    op.create_index("ix_kp_geographies",   "key_points_full", ["geographies"], postgresql_using="gin")
    op.create_index("ix_kp_fts",           "key_points_full", ["kp_fts"],      postgresql_using="gin")

    # ── Trade ideas (denormalised) ───────────────────────────────────────────
    op.create_table(
        "trade_ideas_full",
        sa.Column("trade_idea_id",         sa.String,                  primary_key=True),
        sa.Column("email_content_hash",    sa.String,                  sa.ForeignKey("emails.email_content_hash"), nullable=False),
        sa.Column("email_sent_dt",         sa.DateTime(timezone=True)),
        sa.Column("email_subject",         sa.String),
        sa.Column("file_name",             sa.String),
        sa.Column("source_org",            sa.String),
        sa.Column("suggested_source_org",  sa.String),
        sa.Column("effective_source_org",  sa.String),
        sa.Column("trade_idea_text",       sa.Text,                    nullable=False),
        sa.Column("trade_idea_citation",   sa.Text),
        sa.Column("trade_idea_context",    sa.Text),
        sa.Column("asset_class",           sa.String),
        sa.Column("suggested_asset_class", sa.String),
        sa.Column("time_horizon",          sa.String),
        sa.Column("geographies",           ARRAY(sa.String)),
        sa.Column("suggested_geographies", ARRAY(sa.String)),
        sa.Column("target_price",          sa.String),
        sa.Column("stop_price",            sa.String),
        sa.Column("trigger_condition",     sa.String),
        sa.Column("legs",                  JSONB),
        sa.Column("ti_fts",                TSVECTOR),
    )
    op.execute("ALTER TABLE trade_ideas_full ADD COLUMN ti_embedding vector(1536)")

    op.create_index("ix_ti_source_org_dt",  "trade_ideas_full", ["source_org",  "email_sent_dt"])
    op.create_index("ix_ti_asset_class_dt", "trade_ideas_full", ["asset_class", "email_sent_dt"])
    op.create_index("ix_ti_geographies",    "trade_ideas_full", ["geographies"], postgresql_using="gin")
    op.create_index("ix_ti_fts",            "trade_ideas_full", ["ti_fts"],      postgresql_using="gin")
    op.create_index("ix_ti_sent_dt",        "trade_ideas_full", ["email_sent_dt"])

    # ── Email chunks (parent-child path) ────────────────────────────────────
    op.create_table(
        "email_chunks",
        sa.Column("chunk_id",           sa.String,                  primary_key=True),
        sa.Column("email_content_hash", sa.String,                  sa.ForeignKey("emails.email_content_hash"), nullable=False),
        sa.Column("chunk_index",        sa.Integer,                 nullable=False),
        sa.Column("chunk_text",         sa.Text,                    nullable=False),
        sa.Column("email_sent_dt",      sa.DateTime(timezone=True)),
        sa.Column("email_subject",      sa.String),
        sa.Column("source_org",         sa.String),
    )
    op.execute("ALTER TABLE email_chunks ADD COLUMN chunk_embedding vector(1536)")

    op.create_index("ix_chunk_email_hash", "email_chunks", ["email_content_hash"])
    op.create_index("ix_chunk_sent_dt",    "email_chunks", ["email_sent_dt"])
    op.create_index("ix_chunk_source_org", "email_chunks", ["source_org"])

    # ── Disagreements ────────────────────────────────────────────────────────
    op.create_table(
        "disagreements",
        sa.Column("disagreement_id",  sa.String,                  primary_key=True),
        sa.Column("group_key",        sa.String,                  nullable=False),
        sa.Column("geography",        sa.String),
        sa.Column("window_start",     sa.DateTime(timezone=True)),
        sa.Column("window_end",       sa.DateTime(timezone=True)),
        sa.Column("scale",            sa.String),
        sa.Column("n_banks",          sa.Integer),
        sa.Column("n_keypoints",      sa.Integer),
        sa.Column("sentiment_spread", sa.Integer),
        sa.Column("bank_positions",   JSONB),
    )
    op.create_index("ix_dis_group_key",    "disagreements", ["group_key"])
    op.create_index("ix_dis_window_start", "disagreements", ["window_start"])
    op.create_index("ix_dis_scale",        "disagreements", ["scale"])

    op.create_table(
        "disagreement_validations",
        sa.Column("validation_id",         sa.String,  primary_key=True),
        sa.Column("disagreement_id",       sa.String,  sa.ForeignKey("disagreements.disagreement_id"), nullable=False),
        sa.Column("group_key",             sa.String),
        sa.Column("geography",             sa.String),
        sa.Column("window_start",          sa.DateTime(timezone=True)),
        sa.Column("window_end",            sa.DateTime(timezone=True)),
        sa.Column("status",                sa.String),
        sa.Column("is_false_positive",     sa.Boolean),
        sa.Column("false_positive_reason", sa.String),
        sa.Column("resolution_summary",    sa.String),
        sa.Column("agent_confidence",      sa.Float),
        sa.Column("bank_analysis",         JSONB),
    )
    op.create_index("ix_dv_disagreement_id", "disagreement_validations", ["disagreement_id"])
    op.create_index("ix_dv_is_fp",           "disagreement_validations", ["is_false_positive"])
    op.create_index("ix_dv_status",          "disagreement_validations", ["status"])
    op.create_index("ix_dv_window_start",    "disagreement_validations", ["window_start"])

    # ── Summaries ────────────────────────────────────────────────────────────
    op.create_table(
        "topic_summaries",
        sa.Column("id",           sa.String,                  primary_key=True),
        sa.Column("topic",        sa.String,                  nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end",   sa.DateTime(timezone=True)),
        sa.Column("bullets",      JSONB),
        sa.Column("bullet_count", sa.Integer),
        sa.Column("source_orgs",  ARRAY(sa.String)),
        sa.Column("kp_count",     sa.Integer),
        sa.Column("label_map",    JSONB),
    )
    op.create_index("ix_ts_topic",        "topic_summaries", ["topic"])
    op.create_index("ix_ts_window_start", "topic_summaries", ["window_start"])

    op.create_table(
        "trade_summaries",
        sa.Column("id",           sa.String,                  primary_key=True),
        sa.Column("group_key",    sa.String,                  nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end",   sa.DateTime(timezone=True)),
        sa.Column("bullets",      JSONB),
        sa.Column("bullet_count", sa.Integer),
        sa.Column("source_orgs",  ARRAY(sa.String)),
        sa.Column("kp_count",     sa.Integer),
        sa.Column("label_map",    JSONB),
    )
    op.create_index("ix_trs_group_key",    "trade_summaries", ["group_key"])
    op.create_index("ix_trs_window_start", "trade_summaries", ["window_start"])

    # ── Webinars ─────────────────────────────────────────────────────────────
    op.create_table(
        "webinars",
        sa.Column("webinar_id",       sa.String,                  primary_key=True),
        sa.Column("file_name",        sa.String,                  nullable=False),
        sa.Column("source_bank",      sa.String),
        sa.Column("is_webinar",       sa.Boolean),
        sa.Column("title",            sa.String),
        sa.Column("host_bank",        sa.String),
        sa.Column("event_datetime",   sa.String),
        sa.Column("event_timezone",   sa.String),
        sa.Column("topic_summary",    sa.String),
        sa.Column("speakers",         JSONB),
        sa.Column("url",              sa.String),
        sa.Column("location",         sa.String),
        sa.Column("created_datetime", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_web_source_bank", "webinars", ["source_bank"])
    op.create_index("ix_web_created_dt",  "webinars", ["created_datetime"])
    op.create_index("ix_web_is_webinar",  "webinars", ["is_webinar"])


def downgrade() -> None:
    for tbl in [
        "webinars", "trade_summaries", "topic_summaries",
        "disagreement_validations", "disagreements",
        "email_chunks", "trade_ideas_full", "key_points_full",
        "emails", "geographies", "topics", "source_orgs",
    ]:
        op.drop_table(tbl)
