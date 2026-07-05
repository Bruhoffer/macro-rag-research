"""Test env bootstrap.

Some modules read required env vars (DATABASE_URL, keys) at import time. Set
harmless dummies so unit tests can import app modules without a real DB or
secrets. SQLAlchemy engines and the Anthropic client are lazy, so nothing
actually connects.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("MACRO_RAG_API_KEY", "test")
os.environ.setdefault("ADMIN_API_KEY", "test")
