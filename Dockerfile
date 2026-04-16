# Small, production-grade image. ~180 MB final.
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to build wheels for cryptography / aiosqlite.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

# Only the runtime shared libraries cryptography needs — no compilers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libffi8 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 apex

COPY --from=builder /root/.local /home/apex/.local
COPY --chown=apex:apex apex ./apex
COPY --chown=apex:apex scripts ./scripts
COPY --chown=apex:apex pyproject.toml start.sh ./
RUN chmod +x start.sh && mkdir -p /app/data && chown apex:apex /app/data

USER apex
ENV PATH="/home/apex/.local/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DB_PATH=/app/data/apex.db

# Sanity check — importing all modules at build time catches breakage early.
RUN python scripts/smoke.py

ENTRYPOINT ["./start.sh"]
