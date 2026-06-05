from sqlalchemy import Column, Integer, String, DateTime, Index
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from app.models.base import Base


class TopicSummary(Base):
    __tablename__ = "topic_summaries"

    id           = Column(String, primary_key=True)   # UUID generated at migration time
    topic        = Column(String, nullable=False)
    window_start = Column(DateTime(timezone=True))
    window_end   = Column(DateTime(timezone=True))
    bullets      = Column(JSONB)                       # ["bullet text with [N] footnotes", ...]
    bullet_count = Column(Integer)
    source_orgs  = Column(ARRAY(String))
    kp_count     = Column(Integer)
    label_map    = Column(JSONB)                       # {"[25]": "key_point_uuid", ...}

    __table_args__ = (
        Index("ix_ts_topic",        "topic"),
        Index("ix_ts_window_start", "window_start"),
    )


class TradeSummary(Base):
    __tablename__ = "trade_summaries"

    id           = Column(String, primary_key=True)
    group_key    = Column(String, nullable=False)      # asset_class name
    window_start = Column(DateTime(timezone=True))
    window_end   = Column(DateTime(timezone=True))
    bullets      = Column(JSONB)
    bullet_count = Column(Integer)
    source_orgs  = Column(ARRAY(String))
    kp_count     = Column(Integer)
    label_map    = Column(JSONB)                       # {"[N]": "trade_idea_uuid", ...}

    __table_args__ = (
        Index("ix_trs_group_key",    "group_key"),
        Index("ix_trs_window_start", "window_start"),
    )
