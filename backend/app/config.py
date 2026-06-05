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

EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "claude-sonnet-4-6"

# Path to raw .eml files — relative to the backend/ directory
RAW_EMAILS_DIR = Path(__file__).parent.parent / os.environ.get("RAW_EMAILS_DIR", "../../raw-emails")
