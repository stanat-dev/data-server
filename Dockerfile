# stanat data-server (FastAPI). 스키마는 backend-spring Flyway 소유 —
# DB에 external_places 가 먼저 만들어져 있어야 ingest 가 동작한다.
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

RUN useradd --system --uid 1001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
