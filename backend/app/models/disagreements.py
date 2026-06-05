from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base


class Disagreement(Base):
    __tablename__ = "disagreements"

    disagreement_id  = Column(String, primary_key=True)
    group_key        = Column(String, nullable=False)    # topic name
    geography        = Column(String)
    window_start     = Column(DateTime(timezone=True))
    window_end       = Column(DateTime(timezone=True))
    scale            = Column(String)                    # "High" | "Medium" | "Low"
    n_banks          = Column(Integer)
    n_keypoints      = Column(Integer)
    sentiment_spread = Column(Integer)                   # max_score - min_score (0-4)
    bank_positions   = Column(JSONB)                     # [{source_org, sentiment, geographies[]}]

    validations = relationship("DisagreementValidation", back_populates="disagreement")

    __table_args__ = (
        Index("ix_dis_group_key",    "group_key"),
        Index("ix_dis_window_start", "window_start"),
        Index("ix_dis_scale",        "scale"),
    )


class DisagreementValidation(Base):
    __tablename__ = "disagreement_validations"

    validation_id         = Column(String, primary_key=True)
    disagreement_id       = Column(String, ForeignKey("disagreements.disagreement_id"), nullable=False)
    group_key             = Column(String)
    geography             = Column(String)
    window_start          = Column(DateTime(timezone=True))
    window_end            = Column(DateTime(timezone=True))
    status                = Column(String)    # "resolved" | "inconclusive" | "dismissed" | "false_positive"
    is_false_positive     = Column(Boolean)
    false_positive_reason = Column(String)
    resolution_summary    = Column(String)
    agent_confidence      = Column(Float)
    bank_analysis         = Column(JSONB)     # [{source_org, subject_entity, bull_bear, position_summary, value_claim}]

    disagreement = relationship("Disagreement", back_populates="validations")

    __table_args__ = (
        Index("ix_dv_disagreement_id",  "disagreement_id"),
        Index("ix_dv_is_fp",            "is_false_positive"),
        Index("ix_dv_status",           "status"),
        Index("ix_dv_window_start",     "window_start"),
    )
