FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by cryptography / cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY apex ./apex
COPY scripts ./scripts
COPY pyproject.toml ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

CMD ["python", "-m", "apex.main"]
