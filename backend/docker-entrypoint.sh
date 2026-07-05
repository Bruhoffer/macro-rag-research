#!/bin/sh
# Apply DB migrations, then hand off to uvicorn as PID 1 (via exec) so it
# receives SIGTERM directly for graceful shutdown on the hosting platform.
set -e

alembic upgrade head

# --proxy-headers: honour X-Forwarded-For so the rate limiter keys on the real
# client IP — but only from proxies we trust. FORWARDED_ALLOW_IPS must be set
# per environment (K8s: ingress controller pod CIDR; VPS: docker bridge
# gateway). The 127.0.0.1 default means "trust no external proxy": direct
# clients then can't spoof their IP to dodge per-IP limits.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    --timeout-keep-alive 75
