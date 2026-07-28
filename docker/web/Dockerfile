FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir poetry==1.8.3

COPY pyproject.toml poetry.lock ./

RUN poetry export -f requirements.txt --output requirements.txt \
    --without-hashes --only main

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY --from=builder /build/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN chmod +x /app/docker/entrypoint.sh \
    && groupadd -r appgroup \
    && useradd -r -g appgroup -d /app appuser \
    && chown -R appuser:appgroup /app

USER appuser

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "--factory", "src.main:create_app", \
     "--host", "0.0.0.0", "--port", "8000", "--reload"]
