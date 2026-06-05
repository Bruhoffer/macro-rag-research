from sqlalchemy import Column, String, Boolean, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import Base


class Webinar(Base):
    __tablename__ = "webinars"

    webinar_id       = Column(String, primary_key=True)   # UUID generated at migration
    file_name        = Column(String, nullable=False)
    source_bank      = Column(String)
    is_webinar       = Column(Boolean)
    title            = Column(String)
    host_bank        = Column(String)
    event_datetime   = Column(String)       # kept as string — format varies in raw data
    event_timezone   = Column(String)
    topic_summary    = Column(String)
    speakers         = Column(JSONB)        # [{name, title}]
    url              = Column(String)
    location         = Column(String)
    created_datetime = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_web_source_bank",  "source_bank"),
        Index("ix_web_created_dt",   "created_datetime"),
        Index("ix_web_is_webinar",   "is_webinar"),
    )
