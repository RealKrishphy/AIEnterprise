# API

Run the development server from this directory:

```powershell
python -m pip install -e ".[dev]"
lumen-api --reload
```

The launcher prints the health-check URL (by default `http://127.0.0.1:8000/health/live`) before starting Uvicorn. Configure a different bind address with `--host` and `--port`; the printed URL follows those options. For example, `lumen-api --host 0.0.0.0 --port 8080`.

The liveness endpoint does not require a database:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
```

It returns `{"status":"ok"}`. Database-backed authentication endpoints require PostgreSQL and the Alembic migration to be applied.

## Document ingestion

Apply migrations with `alembic upgrade head`. Uploads require an authenticated bearer token, a
running ClamAV daemon reachable through `LUMEN_CLAMAV_HOST`/`LUMEN_CLAMAV_PORT`, Redis, and an
S3-compatible bucket created at `LUMEN_OBJECT_STORE_ENDPOINT`. The API checks size, extension,
declared media type, and file signature, scans the content before object storage, then queues an
idempotent ingestion task.

Start a worker from this directory with:

```powershell
celery -A lumen.celery_app:celery_app worker --loglevel=INFO --queues=ingest-00,ingest-01,ingest-02,ingest-03,ingest-04,ingest-05,ingest-06,ingest-07,ingest-08,ingest-09,ingest-10,ingest-11,ingest-12,ingest-13,ingest-14,ingest-15,dead-letter
```

Workers parse PDF/DOCX/TXT/MD files, split text into heading-aware overlapping chunks, batch
embed using BGE-small, and upsert tenant-scoped chunks with vector and full-text search data.
Failed jobs retry with backoff and are recorded on the dead-letter queue after the retry limit.
