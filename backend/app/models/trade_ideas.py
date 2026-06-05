from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import relationship
from app.models.base import Base


class TradeIdeaFull(Base):
    """Denormalised table: trade_ideas + trade_ideas_enrichments joined."""

    __tablename__ = "trade_ideas_full"

    trade_idea_id         = Column(String, primary_key=True)
    email_content_hash    = Column(String, ForeignKey("emails.email_content_hash"), nullable=False)
    email_sent_dt         = Column(DateTime(timezone=True))
    email_subject         = Column(String)
    file_name             = Column(String)

    # Source
    source_org            = Column(String)
    suggested_source_org  = Column(String)
    effective_source_org  = Column(String)

    # Content
    trade_idea_text       = Column(Text, nullable=False)
    trade_idea_citation   = Column(Text)
    trade_idea_context    = Column(Text)

    # Enrichments (from trade_ideas_enrichments)
    asset_class           = Column(String)         # "Rates" | "FX" | "Equities" | "Credit" | ...
    suggested_asset_class = Column(String)
    time_horizon          = Column(String)         # "Near-term (0-3m)" | ...
    geographies           = Column(ARRAY(String))
    suggested_geographies = Column(ARRAY(String))
    target_price          = Column(String)
    stop_price            = Column(String)
    trigger_condition     = Column(String)
    legs                  = Column(JSONB)          # [{instrument, direction, action}]

    # Search
    ti_embedding          = Column(Vector(1536))
    ti_fts                = Column(TSVECTOR)

    email = relationship("Email", back_populates="trade_ideas")

    __table_args__ = (
        Index("ix_ti_source_org_dt",  "source_org",   "email_sent_dt"),
        Index("ix_ti_asset_class_dt", "asset_class",  "email_sent_dt"),
        Index("ix_ti_geographies",    "geographies",  postgresql_using="gin"),
        Index("ix_ti_fts",            "ti_fts",       postgresql_using="gin"),
        Index("ix_ti_sent_dt",        "email_sent_dt"),
    )
