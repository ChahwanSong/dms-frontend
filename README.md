# DMS Frontend

A Kubernetes-ready FastAPI microservice that fronts the Data Moving Service (DMS). The frontend accepts user task
requests, persists metadata in Redis, forwards work to the `dms_scheduler`, and exposes rich lifecycle management APIs for end
users and operators.

## Table of contents
- [Architecture overview](#architecture-overview)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the service](#running-the-service)
- [API reference](#api-reference)
- [Usage examples](#usage-examples)
- [Testing](#testing)

## Architecture overview
The service is event driven and composed of the following layers:

- **FastAPI application** (`app/main.py`) mounts three routers: user-facing routes, operator-only routes guarded by an
  `X-Operator-Token` header, and a help endpoint. 
- **Task service** (`app/services/tasks.py`) centralises business logic for creating, listing, cancelling, and cleaning up tasks
  while enforcing service/user scoping rules. 
- **Task repository** (`task_state/repository.py` exposed via `app/services/repository.py`) abstracts persistence with a
  Redis-backed implementation.
- **Event processor** (`app/services/event_processor.py`) handles asynchronous fan-out to the scheduler using a configurable
  pool of worker coroutines. 
- **Scheduler client** (`app/services/scheduler.py`) issues HTTP calls to the `dms_scheduler` `/task` and `/cancel` endpoints
  using URLs from configuration. 
- **Service container** (`app/services_container.py`) wires the above components together, manages Redis connections, and
  configures logging suitable for Kubernetes (JSON structured output via `app/core/logging.py`). 

### Request lifecycle
1. A REST call hits the FastAPI router and is validated by the relevant Pydantic response models. 
2. The `TaskService` persists/updates task records through the repository and publishes an event to the background processor. 
3. Worker coroutines in the `TaskEventProcessor` dequeue events, call the scheduler client, and update status/log entries. 
4. Task state is queryable via Redis-backed repository methods, ensuring horizontally scalable reads in the Kubernetes cluster. 

## Repository layout
```
app/
  api/                # FastAPI routers, dependencies, and security utilities
  core/               # Configuration, logging, and event definitions
  services/           # Task service, repositories, scheduler client, event processor
  services_container.py
task_state/           # Reusable task repository, models, and Redis provider
cli/
  main.py             # Typer CLI entry point ("dms-frontend" console script)
examples/
  external_status_service/  # Minimal worker that reuses the shared Redis repository
tests/
  test_api.py         # Async API tests with a stub repository and stub scheduler
```

## Prerequisites
- Python 3.11+
- Redis cluster (write: `haproxy-redis.dms-redis.svc.cluster.local:6379`, read: `haproxy-redis.dms-redis.svc.cluster.local:6380`)
- Access to the `dms_scheduler` service inside the Kubernetes cluster

## Installation
1. Clone the repository and create a virtual environment.
2. Install the service together with development extras:
   ```bash
   pip install -e .[dev]
   ```
## Configuration
All configuration comes from environment variables with the `DMS_` prefix, provided by `app/core/config.py`. 

| Variable | Default | Purpose |
| --- | --- | --- |
| `DMS_APP_NAME` | `dms-frontend` | Service name reported in metadata |
| `DMS_API_PREFIX` | `/api/v1` | Versioned API root |
| `DMS_REDIS_WRITE_URL` | `redis://haproxy-redis.dms-redis.svc.cluster.local:6379/0` | Redis writer endpoint |
| `DMS_REDIS_READ_URL` | `redis://haproxy-redis.dms-redis.svc.cluster.local:6380/0` | Redis reader endpoint |
| `DMS_REDIS_TASK_TTL_SECONDS` | `7776000` | Expiry (in seconds) applied to task metadata and indexes |
| `DMS_SCHEDULER_BASE_URL` | `http://dms-scheduler` | Base URL for the downstream scheduler |
| `DMS_SCHEDULER_TASK_ENDPOINT` | `/task` | Relative submission path |
| `DMS_SCHEDULER_CANCEL_ENDPOINT` | `/cancel` | Relative cancellation path |
| `DMS_OPERATOR_TOKEN` | `changeme` | Token required in the `X-Operator-Token` header |
| `DMS_EVENT_WORKER_COUNT` | `4` | Number of background event workers |
| `DMS_REQUEST_TIMEOUT_SECONDS` | `10.0` | Scheduler client request timeout |
| `DMS_LOG_LEVEL` | `INFO` | Application log level |
| `DMS_LOG_JSON` | `true` | Emit JSON logs (set `false` for local prettiness) |
| `DMS_CLI_DEFAULT_HOST` | `0.0.0.0` | CLI `serve` host |
| `DMS_CLI_DEFAULT_PORT` | `8000` | CLI `serve` port |
| `DMS_CLI_RELOAD` | `false` | Enable autoreload in development |
Use `dms-frontend show-config` to print the effective configuration at runtime.

## Running the service
### Via the CLI
The package exposes a `dms-frontend` console script:
```bash
dms-frontend serve --host 0.0.0.0 --port 8000
```
The command launches Uvicorn with settings pulled from the environment. Add `--reload` for local hot reloading. 

### Directly with Uvicorn
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In Kubernetes deployments the JSON logger writes to stdout/stderr so that the platform can aggregate logs. 

## API reference
All paths are rooted at `/api/v1` by default.

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/help` | API overview and endpoint listing | None |
| GET | `/services/{service}/users/{user_id}/tasks` | List a user's tasks for a service | None |
| POST | `/services/{service}/users/{user_id}/tasks` | Submit a new task; query parameters become task inputs | None |
| GET | `/services/{service}/tasks/{task_id}?user_id=` | Fetch task status scoped to the user | None |
| POST | `/services/{service}/tasks/{task_id}/cancel?user_id=` | Request task cancellation | None |
| DELETE | `/services/{service}/tasks/{task_id}?user_id=` | Delete task metadata and logs (user-scoped) | None |
| GET | `/admin/tasks` | List all tasks across services | `X-Operator-Token` header |
| GET | `/admin/services/{service}/tasks` | List tasks for a specific service | `X-Operator-Token` header |
| POST | `/admin/tasks/{task_id}/cancel` | Cancel any task | `X-Operator-Token` header |
| DELETE | `/admin/tasks/{task_id}` | Cleanup task metadata/logs | `X-Operator-Token` header |

Task status responses include the latest log entries alongside metadata, so a dedicated log-only endpoint is unnecessary. Each log entry is timestamped using the configured timezone (Asia/Seoul by default) in the format `<iso-timestamp>,<message>` (for example, `2025-11-17T10:00:16.515926+09:00,Dispatching to scheduler`). Set `DMS_TIMEZONE=UTC` if you prefer UTC offsets instead. The `/help` response mirrors this table and is available at `/api/v1/help`.

## Usage examples
Assuming the service is running locally on port 8000:

```bash
# API prefix for convenience
api_prefix="http://localhost:8000/api/v1"

# Submit a synchronous task for user "alice"
curl -X POST "${api_prefix}/services/sync/users/alice/tasks?input=value"

# Submit a task with multiple query params (becomes task inputs)
curl -X POST "${api_prefix}/services/sync/users/alice/tasks" \
  --data "" --get \
  --data-urlencode "input=value" \
  --data-urlencode "mode=fast"

# Fetch task status scoped to the user
task_id="<task-id>"
curl "${api_prefix}/services/sync/tasks/${task_id}?user_id=alice"

# List users who submitted sync tasks
curl "${api_prefix}/services/sync/users"

# List user tasks
curl "${api_prefix}/services/sync/users/alice/tasks"

# Cancel a task
curl -X POST "${api_prefix}/services/sync/tasks/${task_id}/cancel" \
  --data "" --get --data-urlencode "user_id=alice"

# Delete task metadata and logs (user-scoped)
curl -X DELETE "${api_prefix}/services/sync/tasks/${task_id}?user_id=alice"

# Operator listing with token
token="$(printenv DMS_OPERATOR_TOKEN)"
curl "${api_prefix}/admin/tasks" -H "X-Operator-Token: ${token}"

# Operator cancellation of any task
curl -X POST "${api_prefix}/admin/tasks/${task_id}/cancel" -H "X-Operator-Token: ${token}"

# Operator cleanup of task metadata/logs
curl -X DELETE "${api_prefix}/admin/tasks/${task_id}" -H "X-Operator-Token: ${token}"

# Start the service via the Typer CLI (honours env vars for host/port)
dms-frontend serve --host 0.0.0.0 --port 8000

# Interact with the API via the Typer CLI helpers (DMS_API_BASE can also be set)
dms-frontend tasks list --service sync --user alice --api-base "${api_prefix}"
dms-frontend tasks status --service sync --task-id "${task_id}" --api-base "${api_prefix}" --user alice
dms-frontend tasks users --service sync --api-base "${api_prefix}"
dms-frontend tasks submit --service sync --user alice --api-base "${api_prefix}" --param input=value --param mode=fast
dms-frontend tasks cancel --service sync --task-id "${task_id}" --api-base "${api_prefix}" --user alice
dms-frontend tasks delete --service sync --task-id "${task_id}" --api-base "${api_prefix}" --user alice
```

### External status publisher example

The `task_state` package can be reused by other services to write task updates against the same Redis
cluster. The `examples/external_status_service` project provides a minimal asyncio worker that registers a task,
publishes lifecycle events, and appends execution logs using the shared repository helper. Install it in editable
mode alongside the main service to experiment with multi-project integrations.

## Testing
Automated tests rely on stubbed Redis providers and a stub scheduler. To run them:
```bash
pytest
```
The suite exercises task submission, cancellation, and operator authentication flows defined in `tests/test_api.py`. 
