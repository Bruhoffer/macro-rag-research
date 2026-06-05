from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text, DateTime, SmallInteger, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import relationship
from app.models.base import Base


class KeyPointFull(Base):
    """Denormalised table: key_points + key_points_enrichments joined."""

    __tablename__ = "key_points_full"

    key_point_id          = Column(String, primary_key=True)
    email_content_hash    = Column(String, ForeignKey("emails.email_content_hash"), nullable=False)
    email_sent_dt         = Column(DateTime(timezone=True))
    email_subject         = Column(String)        # denormalised from emails
    file_name             = Column(String)         # denormalised — used to build local .eml path

    # Source
    source_org            = Column(String)         # "GS" | "JPM" | "Others"
    suggested_source_org  = Column(String)         # actual name when source_org = "Others"
    effective_source_org  = Column(String)         # COALESCE result — use this in queries

    # Content
    key_point_text        = Column(Text, nullable=False)
    key_point_citation    = Column(Text)           # verbatim quote — used for email body highlighting
    key_point_context     = Column(Text)           # surrounding sentences

    # Enrichments (from key_points_enrichments)
    topics                = Column(ARRAY(String))
    suggested_topics      = Column(ARRAY(String))
    geographies           = Column(ARRAY(String))
    suggested_geographies = Column(ARRAY(String))
    sentiment             = Column(String)         # "very bearish" | "bearish" | "neutral" | "bullish" | "very bullish"
    sentiment_score       = Column(SmallInteger)   # -2 | -1 | 0 | 1 | 2
    time_reference        = Column(String)         # "past" | "present" | "future"
    future_time_horizon   = Column(String)         # "Near-term (0-3m)" | "Medium-term (3-12m)" | "Long-term (1y+)"

    # Search
    kp_embedding          = Column(Vector(1536))   # text-embedding-3-small — populated in Phase 2
    kp_fts                = Column(TSVECTOR)       # BM25 full-text search — populated in Phase 2

    email = relationship("Email", back_populates="key_points")

    __table_args__ = (
        # Scalar filters
        Index("ix_kp_source_org_dt",  "source_org",      "email_sent_dt"),
        Index("ix_kp_sentiment_dt",   "sentiment_score",  "email_sent_dt"),
        Index("ix_kp_time_ref",       "time_reference"),
        Index("ix_kp_sent_dt",        "email_sent_dt"),
        # GIN for arrays (overlap queries: topics && '{Inflation}')
        Index("ix_kp_topics",         "topics",      postgresql_using="gin"),
        Index("ix_kp_geographies",    "geographies", postgresql_using="gin"),
        # GIN for full-text search
        Index("ix_kp_fts",            "kp_fts",      postgresql_using="gin"),
        # HNSW vector index — built after embeddings are populated (Phase 2)
        # Not created here because the column is NULL until Phase 2
    )
