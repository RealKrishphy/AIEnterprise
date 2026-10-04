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
