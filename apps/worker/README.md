# Worker

Celery tasks are currently implemented in `apps/api/lumen/tasks.py` and configured in
`apps/api/lumen/celery_app.py`. Run the worker from `apps/api`; the API README documents the
worker command and required services. The queue is sharded across 16 deterministic tenant queues
to reduce noisy-neighbor effects; production fairness still requires workload measurements and
queue-level monitoring.
