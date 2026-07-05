"""Per-IP rate limiting (HOSTING_PLAN.md B.4).

One shared Limiter so routers can import it for per-route limits. The default
limit is a generous per-IP ceiling on every API route; /api/chat carries its
own much stricter limit (each call is a paid Claude invocation).

In-memory storage — correct for a single-process deployment. If the app is
ever scaled to multiple workers/instances, switch to a Redis storage URI.

NOTE (deploy): behind a reverse proxy, run uvicorn with --proxy-headers so
get_remote_address sees the real client IP, not the proxy's.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

# Each chat call = one paid Claude call (possibly several rounds of tool use).
CHAT_RATE_LIMIT = "5/minute;30/hour"
