from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from app.models.base import Base


class Email(Base):
    __tablename__ = "emails"

    email_content_hash = Column(String, primary_key=True)
    file_name          = Column(String, nullable=False)   # "FW_ GS MORNING.eml"
    email_subject      = Column(String)
    email_from         = Column(String)
    email_to           = Column(String)
    email_sent_dt      = Column(DateTime(timezone=True))
    email_body         = Column(Text)
    email_body_length  = Column(Integer)

    key_points  = relationship("KeyPointFull",  back_populates="email")
    trade_ideas = relationship("TradeIdeaFull", back_populates="email")
    chunks      = relationship("EmailChunk",    back_populates="email")
