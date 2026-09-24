# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir semgrep


# ---- Runtime stage ----
FROM python:3.12-slim

WORKDIR /app

# git is needed to clone PR repos; semgrep needs some shared libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY src/ src/
COPY scripts/ scripts/
COPY pyproject.toml .

# The start script runs both uvicorn and arq
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
