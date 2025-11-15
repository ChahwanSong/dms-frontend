# Task Repository Architecture

This document describes the storage layout and indexing strategy used by `app/services/repository.py` for persisting asynchronous task metadata. Two repository implementations share the same logical model:

* `RedisTaskRepository` — production-grade implementation backed by Redis.
* `InMemoryTaskRepository` — in-process implementation that mirrors the Redis behaviour for tests.

Both implementations operate on `TaskRecord` models from `app/services/models.py`, which capture the task identifier, owning service, user, status, parameters, timestamps, and log messages.

## Redis-backed data layout

`RedisTaskRepository` uses a combination of simple keys and set-based indexes to organise task state. All keys are stored in a single Redis logical database and follow the naming convention described below. Every key that the repository writes is assigned a time-to-live (TTL) configured through `Settings.redis_task_ttl_seconds` (default: 90 days) so that stale metadata is automatically purged.

### Primary task store

* **Key pattern:** `task:{task_id}`
* **Value:** JSON serialisation of the corresponding `TaskRecord`.
* **Purpose:** Acts as the source of truth for each task. Every mutating operation (`save`, `set_status`, `append_log`) overwrites this key with the updated payload.

### Global task index

* **Key:** `index:tasks`
* **Type:** Redis Set
* **Members:** All task IDs currently persisted.
* **Purpose:** Enables `list_all` operations by storing every known task identifier.

### Service index

* **Key pattern:** `index:service:{service}`
* **Type:** Redis Set
* **Members:** Task IDs owned by the specified service.
* **Purpose:** Supports `list_by_service` queries without scanning the entire task store.

### Service + user index

* **Key pattern:** `index:service:{service}:user:{user_id}`
* **Type:** Redis Set
* **Members:** Task IDs scoped to a specific service and user.
* **Purpose:** Backing store for `list_by_service_and_user`, allowing dashboards to filter tasks per customer/user efficiently.

### Identifier sequencing

* **Key:** `task:id:sequence`
* **Type:** Redis String (integer counter)
* **Purpose:** `next_task_id` increments this counter atomically to produce monotonic task IDs.

### Write flow

When a task is saved via `save`:

1. The serialized `TaskRecord` is written to `task:{task_id}`.
2. The task ID is added to the global set `index:tasks`.
3. The task ID is inserted into `index:service:{service}` for service-level filtering.
4. The task ID is inserted into `index:service:{service}:user:{user_id}` for per-user filtering.
5. TTLs on the primary key and each index key are refreshed to honour the configured expiry window.

Deleting a task removes the primary key and prunes its ID from all three index sets.

### Status and log updates

`set_status` and `append_log` load the `TaskRecord`, mutate its status or log list, update the `updated_at` timestamp, and call `save` to persist the changes. Because `save` rewrites the primary store and refreshes the index memberships, the indexes stay in sync automatically.

## In-memory mirror implementation

`InMemoryTaskRepository` mimics the Redis behaviour using Python dictionaries and sets:

* `_store` maps task IDs to `TaskRecord` instances, equivalent to `task:{task_id}`.
* `_service_index` maps a service name to a `set` of task IDs.
* `_service_user_index` maps `(service, user_id)` tuples to a `set` of task IDs.
* `_sequence` is an integer counter producing IDs for `next_task_id`.

Because the in-memory repository exposes the same interface and maintains the same secondary indexes, it can be used interchangeably in tests to validate service logic without requiring Redis.

## Query capabilities

The repository interface exposed by `TaskRepository` supports the following access patterns:

* Direct lookup by task ID (`get`).
* Bulk fetch for arbitrary ID collections (`list_by_ids`).
* Full inventory listing (`list_all`).
* Service-scoped listing (`list_by_service`).
* Combined service and user filtering (`list_by_service_and_user`).

All implementations are expected to maintain the indexes described above to guarantee that the queries return consistent, up-to-date results.
