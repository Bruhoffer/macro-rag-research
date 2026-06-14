from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class ChatTrace(Base):
    __tablename__ = "chat_traces"

    trace_id              = Column(UUID(as_uuid=True), primary_key=True)
    created_at            = Column(DateTime(timezone=True), server_default=text("now()"))
    user_query            = Column(Text)
    request_messages      = Column(JSONB)
    final_answer          = Column(Text)
    model                 = Column(String)
    n_rounds              = Column(Integer)
    input_tokens          = Column(Integer)
    output_tokens         = Column(Integer)
    cache_read_tokens     = Column(Integer)
    cache_creation_tokens = Column(Integer)
    stop_reason           = Column(String)
    status                = Column(String)   # ok | error | max_rounds
    error_message         = Column(Text)
    duration_ms           = Column(Integer)

    tool_calls = relationship(
        "ToolCallTrace", back_populates="trace",
        order_by="ToolCallTrace.round_index", cascade="all, delete-orphan",
    )


class ToolCallTrace(Base):
    __tablename__ = "tool_call_traces"

    id           = Column(UUID(as_uuid=True), primary_key=True)
    trace_id     = Column(UUID(as_uuid=True), ForeignKey("chat_traces.trace_id", ondelete="CASCADE"), nullable=False)
    round_index  = Column(Integer)
    tool_name    = Column(String)
    tool_input   = Column(JSONB)
    tool_output  = Column(JSONB)
    result_count = Column(Integer)
    duration_ms  = Column(Integer)
    created_at   = Column(DateTime(timezone=True), server_default=text("now()"))

    trace = relationship("ChatTrace", back_populates="tool_calls")


class ApiRequestLog(Base):
    __tablename__ = "api_request_log"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at   = Column(DateTime(timezone=True), server_default=text("now()"))
    method       = Column(String)
    path         = Column(String)
    query_params = Column(JSONB)
    status_code  = Column(Integer)
    duration_ms  = Column(Integer)
    client_host  = Column(String)
