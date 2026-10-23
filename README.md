# Event-Driven Transaction Compliance & Fraud Detection Pipeline

A portfolio-grade, event-driven backend that accepts payment transactions quickly, screens
them asynchronously against a configurable compliance rule engine, and records every decision
in an append-only audit trail.

The API returns `202 Accepted` immediately after persisting the transaction. A Celery worker
evaluates it through independent compliance rules and moves it to `APPROVED`, `FLAGGED`, or
`REJECTED`. Flagged transactions are exposed to a compliance officer for manual review.

## Architecture

```
                    ┌────────────────────────────────────────────────────────────┐
                    │                        FastAPI (api)                       │
 Client ──POST─────▶│  validate schema → persist PENDING_REVIEW → publish event  │
                    └───────────────┬───────────────────────────┬────────────────┘
                                    │                           │
                              ┌─────▼─────┐               ┌─────▼─────┐
                              │ PostgreSQL│               │   Redis   │
                              │           │               │  (broker) │
                              └─────▲─────┘               └─────┬─────┘
                                    │                           │
                    ┌───────────────┴───────────────┐   ┌───────▼────────┐
                    │      Compliance Rule Engine   │◀──│ Celery worker  │
                    │  Velocity / High-risk / KYC   │   │ evaluate task  │
                    └───────────────┬───────────────┘   └────────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  compliance_logs   │
                          │ append-only audit  │
                          └────────────────────┘

 Celery Beat ── every 60s ──▶ re-publish transactions stuck in PENDING_REVIEW
```

### Request lifecycle

1. `POST /transactions` validates the payload with Pydantic and checks that both users exist.
2. The transaction is committed with status `PENDING_REVIEW`.
3. An evaluation task is published to Redis **after** the commit, so the worker can always
   see the row. If publishing fails, ingestion still succeeds; Celery Beat later republishes
   stale pending transactions.
4. The worker loads the transaction, evaluates every rule, writes one `compliance_logs` row
   per violation, and updates the status.
5. A compliance officer lists flagged/rejected transactions and records a manual decision,
   which is also audited.

## Tech stack

| Concern | Choice |
| --- | --- |
| API | FastAPI + Uvicorn |
| Validation | Pydantic v2 / pydantic-settings |
| Persistence | SQLAlchemy 2.0 + PostgreSQL |
| Async processing | Celery 5 + Redis (broker and result backend) |
| Testing | Pytest + in-memory SQLite + FastAPI TestClient |
| Deployment | Docker Compose (api, worker, beat, PostgreSQL, Redis) |

## Features

- Fast `202 Accepted` ingestion with strict, `extra="forbid"` validation.
- Extensible Strategy/registry rule engine — add a class, no central `if/else` edits.
- Audit log with rule code, rule name, severity, human-readable reason, and structured details.
- Idempotent ingestion via an optional `Idempotency-Key` header scoped per sender.
- Idempotent worker evaluation: duplicate Celery deliveries are safe.
- Fail-closed rule evaluation: a crashing rule flags the transaction rather than approving it.
- Manual review workflow that is itself audited.
- Periodic stale-dispatch recovery task for at-least-once event delivery.
- Currency-normalised KYC threshold using a mock FX table.
- Health probes, OpenAPI docs, Docker images, and a 49-test suite.

## Project layout

```
transaction-compliance-engine/
├── app/
│   ├── api/
│   │   ├── deps.py                 # DB session dependency
│   │   └── routes/                 # transactions, users, admin
│   ├── core/
│   │   ├── celery_app.py           # Celery configuration + beat schedule
│   │   ├── config.py               # Pydantic settings
│   │   ├── database.py             # Engine/session factory, create_all
│   │   ├── enums.py                # Status, severity, currency, review enums
│   │   └── time.py                 # UTC helper
│   ├── models/                     # SQLAlchemy models + UTC/type helpers
│   ├── schemas/                    # Pydantic request/response schemas
│   ├── services/
│   │   ├── compliance/             # Rule abstraction, registry, rules, engine
│   │   ├── compliance_service.py   # Evaluate + persist decision/audit logs
│   │   ├── transaction_service.py  # Create, fetch, review, requeue
│   │   ├── dispatch.py             # Broker publishing boundary
│   │   ├── fx.py                   # Mock FX conversion
│   │   └── exceptions.py           # Domain errors
│   ├── workers/tasks.py            # Celery evaluation + stale dispatch tasks
│   └── main.py                     # App factory, routers, health probes
├── scripts/local_services.sh       # User-space PostgreSQL/Redis helper (no Docker)
├── tests/                          # Rule, engine, API, worker integration tests
├── docker-compose.yml
├── Dockerfile
├── requirements.txt / requirements-dev.txt
├── pyproject.toml                  # Pytest, coverage, Ruff configuration
└── .env.example
```

## Quick start (Docker)

Prerequisite: Docker with Compose v2.

```bash
docker compose up --build -d
docker compose ps
```

| Service | Purpose | Port |
| --- | --- | --- |
| `api` | FastAPI | http://localhost:8000 |
| `worker` | Celery worker (2 processes) | — |
| `beat` | Celery Beat scheduler | — |
| `db` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |

- Interactive API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health/live> and `/health/ready`

The API runs `Base.metadata.create_all()` on startup when `AUTO_CREATE_TABLES=true` (the
Compose default). This is a local-development convenience; see **Production notes**.

Stop and remove data:

```bash
docker compose down -v
```

## Local development (no Docker)

Requirements: Python 3.12+, PostgreSQL, Redis.

If PostgreSQL and Redis are installed but not running, start them first. The included
helper supports a user-space install under `~/.local/share/compliance-services` (useful on
macOS when Docker is unavailable and Homebrew's prefix is not writable):

```bash
# One-time, only if the helper reports missing binaries:
# conda create -p "$HOME/.local/share/compliance-services" -c conda-forge postgresql=16 redis-server

./scripts/local_services.sh start    # start PostgreSQL + Redis
./scripts/local_services.sh status
./scripts/local_services.sh stop
```

On other machines, use your package manager's PostgreSQL/Redis services instead and adjust
`DATABASE_URL` / `REDIS_URL` in `.env`.

```bash
cp .env.example .env                 # adjust DATABASE_URL/REDIS_URL if needed
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Terminal 1 – API
.venv/bin/uvicorn app.main:app --reload

# Terminal 2 – worker
.venv/bin/celery -A app.core.celery_app worker --loglevel=INFO

# Terminal 3 – scheduler (enables stale-transaction recovery)
.venv/bin/celery -A app.core.celery_app beat --loglevel=INFO
```

The worker pool defaults to `solo` on macOS and `prefork` on Linux. Celery's prefork pool
can fail on macOS/Python 3.13 because of spawn-based multiprocessing; override with
`CELERY_WORKER_POOL` only if you need a different pool.

Run quality checks:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/pytest --cov=app --cov-report=term-missing
```

Tests use an in-memory SQLite database and stub task publishing, so they need neither
PostgreSQL nor Redis.

## API walkthrough

### 1. Create two customers

```bash
curl -s http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "alice@example.com",
    "full_name": "Alice",
    "country_code": "US",
    "risk_score": 10,
    "kyc_verified": false
  }'
```

```bash
curl -s http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "bob@example.com",
    "full_name": "Bob",
    "country_code": "GB",
    "risk_score": 30,
    "kyc_verified": false
  }'
```

### 2. Submit a transaction

Replace the UUIDs with the IDs returned above.

```bash
curl -s -i http://localhost:8000/transactions \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: transfer-2026-0001' \
  -d '{
    "sender_id": "<ALICE_UUID>",
    "receiver_id": "<BOB_UUID>",
    "amount": "15000.00",
    "currency": "USD",
    "description": "Invoice settlement"
  }'
```

Response (`202 Accepted`):

```json
{
  "transaction_id": "6f1c8f6e-8a1a-4c6f-9f36-2f0a55bdcb5a",
  "status": "PENDING_REVIEW",
  "replayed": false,
  "message": "Transaction accepted for compliance review"
}
```

Repeating the request with the same `Idempotency-Key` and sender returns the same transaction
with `"replayed": true` and publishes no second task.

### 3. Inspect the decision and audit trail

```bash
curl -s http://localhost:8000/transactions/<TRANSACTION_UUID>
```

A worker typically finishes in milliseconds. A large USD transfer from a non-KYC customer
produces `FLAGGED` and a `LARGE_TRANSACTION_KYC` log.

### 4. Compliance-officer queue

```bash
# Both FLAGGED and REJECTED by default
curl -s 'http://localhost:8000/admin/flagged-transactions?limit=25&offset=0'

# Filter to one status
curl -s 'http://localhost:8000/admin/flagged-transactions?status=FLAGGED'
```

### 5. Manual review

```bash
curl -s http://localhost:8000/admin/transactions/<TRANSACTION_UUID>/review \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "APPROVED",
    "reviewer": "officer@example.com",
    "notes": "Source of funds verified."
  }'
```

Only `FLAGGED` transactions can be reviewed. The decision updates the status, records
`reviewed_by` / `reviewed_at` / `review_notes`, and appends a `MANUAL_REVIEW` audit row.

### 6. Re-publish a pending transaction

```bash
curl -s -X POST http://localhost:8000/admin/transactions/<TRANSACTION_UUID>/reevaluate
```

Useful after a broker outage. Non-pending transactions return `409 Conflict`.

## Compliance rules

| Code | Trigger | Outcome |
| --- | --- | --- |
| `VELOCITY_CHECK` | More than `VELOCITY_MAX_TRANSACTIONS` (default 3) including the current transaction in the rolling `VELOCITY_WINDOW_SECONDS` (default 300s) | `FLAGGED` |
| `HIGH_RISK_COUNTRY` | Receiver's country is in `HIGH_RISK_COUNTRIES` (default `KP,IR,SY,CU,SD,MM,BY`) | `REJECTED` |
| `LARGE_TRANSACTION_KYC` | USD-normalised amount exceeds `LARGE_TRANSACTION_THRESHOLD_USD` (default 10,000) and the sender is not KYC verified | `FLAGGED` |

Decision precedence: `REJECTED` > `FLAGGED` > `APPROVED`. Every rule runs even after a
rejection so the audit trail is complete. A rule that raises an exception is converted into
a `RULE_EXECUTION_ERROR` flag (fail closed).

### Adding a rule

Rules are discovered through a registry. Create a class, decorate it, and ensure the module
is imported (the built-ins live in `app/services/compliance/rules.py`).

```python
from app.core.enums import Severity
from app.services.compliance.base import ComplianceRule, register_rule
from app.services.compliance.types import RuleContext, RuleViolation


@register_rule
class UnusualRiskScoreRule(ComplianceRule):
    code = "ELEVATED_RISK_SCORE"
    name = "Elevated customer risk score"
    severity = Severity.FLAG
    order = 40

    def evaluate(self, context: RuleContext) -> RuleViolation | None:
        if context.sender.risk_score < 80:
            return None
        return self.violation(
            f"Sender risk score {context.sender.risk_score} is elevated",
            details={"risk_score": context.sender.risk_score},
        )
```

No API or worker changes are required; the next worker task picks up the new rule.

## Data model

**`users`** — `id`, `email` (unique), `full_name`, `country_code`, `risk_score` (0–100),
`kyc_verified`, `created_at`, `updated_at`.

**`transactions`** — `id`, `sender_id`, `receiver_id`, `amount` (`NUMERIC(18,2)`),
`currency`, `description`, `status`, server-generated `created_at`, `updated_at`,
`idempotency_key`, review metadata.

**`compliance_logs`** — `id`, `transaction_id`, `rule_code`, `rule_name`, `severity`,
`message`, `details` (JSON), `created_at`. Rows are append-only and survive rule renames
because all descriptive fields are denormalised into the row.

### Statuses

| Status | Meaning |
| --- | --- |
| `PENDING_REVIEW` | Accepted and queued; no decision yet |
| `APPROVED` | All rules passed, or a human approved a flag |
| `FLAGGED` | At least one non-blocking rule failed; manual review required |
| `REJECTED` | A blocking rule failed (sanctions/high-risk destination), or a human rejected it |

## Configuration

All settings are environment variables (optionally via `.env`). See `.env.example`.

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | `local`, `test`, `staging`, `production` |
| `AUTO_CREATE_TABLES` | `true` | Development only |
| `DATABASE_URL` | local PostgreSQL DSN | SQLAlchemy URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Broker + result backend fallback |
| `CELERY_BROKER_URL` | unset → `REDIS_URL` | Explicit broker override |
| `CELERY_RESULT_BACKEND` | unset → `REDIS_URL` | Explicit backend override |
| `CELERY_WORKER_POOL` | OS default | `solo` on macOS, `prefork` on Linux |
| `VELOCITY_WINDOW_SECONDS` | `300` | Rolling window |
| `VELOCITY_MAX_TRANSACTIONS` | `3` | Inclusive limit |
| `HIGH_RISK_COUNTRIES` | `KP,IR,SY,CU,SD,MM,BY` | Comma-separated ISO alpha-2 |
| `LARGE_TRANSACTION_THRESHOLD_USD` | `10000` | Must be positive |
| `STALE_PENDING_SECONDS` | `120` | Recovery threshold for pending rows |
| `STALE_DISPATCH_BATCH_SIZE` | `100` | Maximum re-publishes per beat tick |

## Design decisions

- **Postgres commit before publish.** Publishing inside an open transaction can hand a worker
  an ID it cannot read yet. Committing first trades a small delivery gap (recovered by the
  stale dispatcher) for correctness.
- **At-least-once events, idempotent consumers.** Redis/Celery cannot guarantee exactly-once
  delivery. Evaluation uses `SELECT ... FOR UPDATE`, skips terminal transactions, and a unique
  `(sender_id, idempotency_key)` constraint keeps ingestion duplicates out.
- **Server-generated timestamps.** Clients cannot backdate transactions to evade the velocity
  window.
- **Registry + Strategy pattern.** Rules are small, named, independently testable classes with
  an explicit severity. Adding one does not touch the engine, API, or worker.
- **Fail closed.** Rule exceptions become flags; unexpected worker errors leave the transaction
  pending so the recovery task can retry it.
- **Denormalised audit fields.** Logs remain meaningful even if a rule is later renamed or
  deleted.
- **Synchronous SQLAlchemy.** Celery workers are synchronous; using the same session style in
  the API avoids maintaining two persistence stacks. FastAPI runs sync endpoints in its
  threadpool, so the event loop is not blocked.
- **Currency normalisation.** The large-transaction threshold compares USD-equivalent amounts
  from a mock FX table, preventing a currency-denomination bypass. Production should persist
  the rate used at decision time.

## Production notes

This project is intentionally self-contained. Before using it for real money movement:

1. Replace `create_all` with versioned migrations (e.g. Alembic) and set
   `AUTO_CREATE_TABLES=false`.
2. Add authentication/authorisation; compliance-officer endpoints must be restricted and
   role-checked. Add immutable reviewer identities.
3. Replace the mock FX table with a rate provider and store the applied rate on the audit row.
4. Use a real sanctions/PEP screening provider and jurisdiction lists with effective dates.
5. Consider the transactional outbox pattern if broker publishing must be atomic with the
   database commit.
6. Store audit logs in append-only storage with retention policies and tamper evidence.
7. Add structured JSON logging, tracing, metrics (queue depth, evaluation latency, flag rate),
   and alerting.
8. Rate-limit ingestion and add request IDs for end-to-end correlation.
9. Pin and scan dependencies; run workers with a non-root user (the provided image does).

## Troubleshooting

### `connection to server at "localhost", port 5432 failed: Connection refused`

PostgreSQL is not running (or `DATABASE_URL` points at the wrong host/port). Start it:

```bash
./scripts/local_services.sh start             # user-space local install
# or
docker compose up -d db redis
```

Verify with `pg_isready -h localhost -p 5432` and `redis-cli -p 6379 ping`.

### `ValueError: not enough values to unpack (expected 3, got 0)` in the Celery worker

This is a Celery prefork/spawn incompatibility on macOS with Python 3.13. The app
automatically selects the `solo` pool on macOS. If you set `CELERY_WORKER_POOL=prefork`
in `.env`, remove it (or run with `--pool=solo`).

### Transactions stay in `PENDING_REVIEW`

Check that both the worker and beat are running and connected to Redis. The beat process
re-publishes pending transactions older than `STALE_PENDING_SECONDS`. You can also force a
retry:

```bash
curl -X POST http://localhost:8000/admin/transactions/<UUID>/reevaluate
```

## Roadmap mapping

| Phase | Delivered |
| --- | --- |
| 1. API + database | Docker Compose (Postgres/Redis), SQLAlchemy user/transaction models, Pydantic schemas, user and transaction endpoints |
| 2. Async trigger | Celery app, Redis broker, `202` ingestion, post-commit publish, worker task |
| 3. Rule engine | Registry-based Strategy pattern with velocity, high-risk country, and KYC threshold rules, plus tests |
| 4. Audit + monitoring | Per-rule audit logs, flagged-transactions endpoint, manual review, re-evaluation, health probes, stale-dispatch recovery |
