from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import ARRAY
from app.models.base import Base


class SourceOrg(Base):
    __tablename__ = "source_orgs"

    org_shortform_name = Column(String, primary_key=True)   # "GS", "JPM", "Barclays"
    org_name           = Column(String)                      # "Goldman Sachs"
    org_aliases        = Column(ARRAY(String))               # ["Goldman", "Goldman Sachs Research"]
    is_active          = Column(Boolean, default=True)


class Topic(Base):
    __tablename__ = "topics"

    topic_name  = Column(String, primary_key=True)
    description = Column(String)                             # full description shown to LLM
    is_active   = Column(Boolean, default=True)


class Geography(Base):
    __tablename__ = "geographies"

    geography_name = Column(String, primary_key=True)        # "US", "CHN", "EM", "EMEA"
    description    = Column(String)                          # "Emerging Markets"
    is_active      = Column(Boolean, default=True)
