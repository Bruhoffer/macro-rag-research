import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def _require(key: str) -> str:
    """Return env var. Raises only when the DB URL is missing (required to start)."""
    return os.environ.get(key, "")


DATABASE_URL: str = os.environ["DATABASE_URL"]   # must exist to boot
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

# Access model (HOSTING_PLAN.md B.2/B.4/B.5):
#   "open"    — public demo: browse/chat need no key (rate limits + budget cap protect cost)
#   "private" — every /api/* call requires MACRO_RAG_API_KEY (fail-closed 503 if unset)
ACCESS_MODE: str = os.environ.get("ACCESS_MODE", "private")
MACRO_RAG_API_KEY: str = _require("MACRO_RAG_API_KEY")

# Admin dashboard key — /api/admin/* ALWAYS requires this, in both modes (fail-closed).
ADMIN_API_KEY: str = _require("ADMIN_API_KEY")

# Hard ceiling on total estimated Claude spend per UTC day across all users.
CHAT_DAILY_BUDGET_USD: float = float(os.environ.get("CHAT_DAILY_BUDGET_USD", "5"))

# The only origin allowed to make cross-origin API calls (same-origin needs no CORS).
ALLOWED_ORIGIN: str = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000")

EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "claude-sonnet-4-6"

# Path to raw .eml files — relative to the backend/ directory
RAW_EMAILS_DIR = Path(__file__).parent.parent / os.environ.get("RAW_EMAILS_DIR", "../../raw-emails")
