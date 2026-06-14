"""Observability tables — chat traces, tool call traces, api request log

Revision ID: 002
Revises: 001
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Chat traces (one row per /api/chat request) ──────────────────────────
    op.create_table(
        "chat_traces",
        sa.Column("trace_id",              UUID(as_uuid=True),         primary_key=True),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("user_query",            sa.Text),
        sa.Column("request_messages",      JSONB),
        sa.Column("final_answer",          sa.Text),
        sa.Column("model",                 sa.String),
        sa.Column("n_rounds",              sa.Integer),
        sa.Column("input_tokens",          sa.Integer),
        sa.Column("output_tokens",         sa.Integer),
        sa.Column("cache_read_tokens",     sa.Integer),
        sa.Column("cache_creation_tokens", sa.Integer),
        sa.Column("stop_reason",           sa.String),
        sa.Column("status",                sa.String),   # ok | error | max_rounds
        sa.Column("error_message",         sa.Text),
        sa.Column("duration_ms",           sa.Integer),
    )
    op.create_index("ix_chat_traces_created_at", "chat_traces", [sa.text("created_at DESC")])

    # ── Tool call traces (one row per tool call within a chat) ───────────────
    op.create_table(
        "tool_call_traces",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id",     UUID(as_uuid=True),
                  sa.ForeignKey("chat_traces.trace_id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_index",  sa.Integer),
        sa.Column("tool_name",    sa.String),
        sa.Column("tool_input",   JSONB),
        sa.Column("tool_output",  JSONB),
        sa.Column("result_count", sa.Integer),
        sa.Column("duration_ms",  sa.Integer),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_tool_call_traces_trace_id",  "tool_call_traces", ["trace_id"])
    op.create_index("ix_tool_call_traces_tool_name", "tool_call_traces", ["tool_name"])

    # ── API request log (one row per non-chat /api/* request) ────────────────
    op.create_table(
        "api_request_log",
        sa.Column("id",           sa.BigInteger,              primary_key=True, autoincrement=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("method",       sa.String),
        sa.Column("path",         sa.String),
        sa.Column("query_params", JSONB),
        sa.Column("status_code",  sa.Integer),
        sa.Column("duration_ms",  sa.Integer),
        sa.Column("client_host",  sa.String),
    )
    op.create_index("ix_api_request_log_created_at", "api_request_log", [sa.text("created_at DESC")])
    op.create_index("ix_api_request_log_path",       "api_request_log", ["path"])


def downgrade() -> None:
    for tbl in ["api_request_log", "tool_call_traces", "chat_traces"]:
        op.drop_table(tbl)
