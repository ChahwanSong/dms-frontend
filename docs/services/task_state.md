# Shared `task_state` package

This document explains how to consume the `task_state` package from other projects so they can publish task lifecycle updates to the same Redis datastore as the DMS frontend. The package bundles:

- Pydantic models (`TaskRecord`, `TaskStatus`, `TaskResult`) that encode task metadata.
- A Redis-backed repository (`RedisTaskRepository`) that enforces consistent key/index management.
- A connection helper (`RedisRepositoryProvider`) that handles client setup and teardown.

## Installation

Add the repository to your Python environment (for example, as a git submodule or by installing in editable mode alongside your service):

```bash
pip install -e /path/to/dms-frontend
```

External projects can then import `task_state` directly without taking any internal DMS dependencies.

## Configuration

`RedisRepositorySettings.from_env()` reads the following environment variables with sensible defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DMS_REDIS_WRITE_URL` | required | Redis URL used for writes and (if no read URL is supplied) reads. |
| `DMS_REDIS_READ_URL` | value of `DMS_REDIS_WRITE_URL` | Optional Redis URL used for read-only operations. |
| `DMS_REDIS_TASK_TTL_SECONDS` | `7776000` (90 days) | TTL applied to task metadata and all Redis indexes. |
| `DMS_TIMEZONE` | `Asia/Seoul` | Timezone applied to created/updated timestamps and encoded log prefixes. |

You can override the defaults programmatically by instantiating `RedisRepositorySettings` directly.

## Quickstart

```python
from task_state import TaskRecord, TaskStatus
from task_state.redis import RedisRepositoryProvider, RedisRepositorySettings

settings = RedisRepositorySettings.from_env()
provider = RedisRepositoryProvider(settings)
repository = await provider.get_repository()

# Register a task
await repository.save(
    TaskRecord(task_id="external-1", service="analytics", user_id="alice", status=TaskStatus.PENDING)
)

# Push status updates and logs
await repository.set_status("external-1", TaskStatus.RUNNING, log_entry="worker started")
await repository.append_log("external-1", "processed input payload")
await repository.update_result(
    "external-1",
    pod_status="phase=Running",  # stringified pod status snapshot
    launcher_output="streamed stdout/stderr",
)
await repository.set_status("external-1", TaskStatus.COMPLETED, log_entry="worker finished")

await provider.close()
```

The repository automatically refreshes key TTLs and updates the service/user indexes described in `docs/services/repository.md`.
Each log entry is prefixed with an ISO 8601 timestamp in the configured timezone in the form `<timestamp>,<message>` (for example, `2025-11-17T10:00:16.515926+09:00,worker started`). Use `task_state.repository.format_log_entry` if you need to mirror the log encoding elsewhere.

### Result payloads

`TaskRecord.result` holds optional structured outputs from the workload. It is intended for Kubernetes pod status snapshots (stored as strings, such as JSON-encoded pod status) and combined launcher output (stdout and stderr coalesced into a single string). `update_result` is additive: only fields passed to the method are overwritten, making it safe for multiple processes to add pod state or output independently.

### Job identifiers

`TaskRecord.jobs` stores any job identifiers assigned by external schedulers. The list defaults to empty so callers can choose when to populate it (for example, after a scheduler returns the job ID on submission).

## Testing in downstream projects

When unit-testing an integration that depends on the shared repository, stub out the Redis clients to avoid network calls. The `tests/test_task_state.py` file in this repository demonstrates patching `Redis.from_url` with mocks so the provider returns a lightweight repository while still exercising key behaviours (ping checks and connection cleanup).
