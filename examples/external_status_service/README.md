# External Status Service 예제

`examples/external_status_service` 폴더에는 Redis를 통해 장기 실행 작업의 상태를 공유하는 간단한 워커 예제가 포함되어 있습니다. `task_state` 패키지를 사용해 작업 메타데이터를 직렬화하고, 상태 변경 시 로그를 남기며, 만료 처리까지 재사용할 수 있도록 구성되어 있습니다.

## 폴더 구조

- `worker.py`: Redis 레포지토리에 작업을 저장하고 상태 변화를 게시하는 최소 워커 구현.
- `pyproject.toml`: 워커 실행에 필요한 의존성과 로컬 개발 시 `task_state`를 불러오는 `local` extra 정의.

## 실행 준비

1. **Redis 실행**: 로컬 또는 접근 가능한 Redis 인스턴스가 필요합니다.
2. **환경 변수 설정**:
   - `DMS_REDIS_WRITE_URL`: Redis 쓰기용 URL (예: `redis://localhost:6379/0`).
   - `DMS_REDIS_READ_URL`: Redis 읽기용 URL. 지정하지 않으면 쓰기 URL을 재사용합니다.
   - `DMS_REDIS_TASK_TTL_SECONDS`(선택): 작업 TTL. 기본값은 90일.
   - `DMS_TIMEZONE`(선택): 예: `Asia/Seoul`.
3. **의존성 설치**:

```bash
cd examples/external_status_service
python -m venv .venv
source .venv/bin/activate
pip install -e .[local]
```

## 실행 방법

기본 워커는 `demo` 작업을 등록하고, 짧은 지연 후 완료 상태로 업데이트합니다.

```bash
external-status-worker
```

출력 로그 예시:

```
INFO:__main__:Registering task demo as RUNNING
INFO:__main__:Marking task demo as COMPLETED
```

## 코드 흐름 요약

1. `RedisRepositorySettings.from_env()`로 Redis 연결 정보를 읽어옵니다.
2. `RedisRepositoryProvider`가 비동기 Redis 클라이언트를 생성하고 `RedisTaskRepository` 인스턴스를 반환합니다.
3. `TaskStatusPublisher`가 `TaskRecord`를 저장하고 상태를 `RUNNING → COMPLETED`(또는 실패 시 `FAILED`)로 변경하며 로그를 남깁니다.
4. 모든 작업이 끝나면 Redis 연결을 정리합니다.

`worker.py`에서 핵심 부분은 다음과 같습니다.

```python
settings = RedisRepositorySettings.from_env()
provider = RedisRepositoryProvider(settings)
publisher = TaskStatusPublisher(provider)

# 새로운 작업 등록
await publisher.publish_start(
    TaskRecord(
        task_id=task_id,
        service=service,
        user_id=user_id,
        status=TaskStatus.PENDING,
    )
)

# 실제 작업 실행 후 완료 처리
result = await _simulate_work(task_id)
await publisher.publish_completion(task_id, result)
```

## `task_state`를 활용한 추가 예제

아래는 README만 보고도 따라 해볼 수 있는 간단한 코드 조각들입니다.

### 1) TaskRecord 생성과 로그 추가

```python
from task_state import TaskRecord, TaskStatus
from task_state.repository import format_log_entry
from task_state.timezone import now

# 새 작업 생성
record = TaskRecord(
    task_id="123",
    service="report",
    user_id="alice",
    status=TaskStatus.PENDING,
)

# 상태 갱신과 로그 추가
record.status = TaskStatus.RUNNING
record.updated_at = now()
record.logs.append(format_log_entry("Worker picked up the job"))
record.logs.append(format_log_entry("Streaming partial result"))
```

### 2) Redis 레포지토리로 저장/조회/상태 변경

```python
import asyncio
from task_state import TaskRecord, TaskStatus
from task_state.redis import RedisRepositoryProvider, RedisRepositorySettings

async def main() -> None:
    settings = RedisRepositorySettings.from_env()
    provider = RedisRepositoryProvider(settings)
    repo = await provider.get_repository()

    # ID 시퀀스에서 새 ID 발급 후 저장
    task_id = await repo.next_task_id()
    task = TaskRecord(
        task_id=task_id,
        service="etl",
        user_id="bob",
        status=TaskStatus.PENDING,
        parameters={"source": "s3"},
    )
    await repo.save(task)

    # 상태 변경과 로그 추가
    await repo.set_status(task_id, TaskStatus.RUNNING, log_entry="started")
    await repo.append_log(task_id, "halfway done")
    await repo.set_status(task_id, TaskStatus.COMPLETED, log_entry="finished")

    # 확인
    restored = await repo.get(task_id)
    print(restored.model_dump())

    await provider.close()

asyncio.run(main())
```

### 3) 간단한 인메모리 흐름 시뮬레이션

Redis가 필요 없는 가장 단순한 흐름을 빠르게 확인하고 싶다면, `TaskRecord`만으로 상태 전이를 시뮬레이션할 수 있습니다.

```python
from task_state import TaskRecord, TaskStatus
from task_state.timezone import now

# 초기 상태
record = TaskRecord(
    task_id="dry-run",
    service="diagnostics",
    user_id="cli",
    status=TaskStatus.PENDING,
)

# Dispatch → Running → Completed 순서로 갱신
for status in (TaskStatus.DISPATCHING, TaskStatus.RUNNING, TaskStatus.COMPLETED):
    record.status = status
    record.updated_at = now()
    print(f"{record.task_id}: {record.status} at {record.updated_at}")
```

이 예제들은 `task_state`가 제공하는 `TaskRecord`, `TaskStatus`, 로그 포맷터, Redis 레포지토리 제공자를 어떻게 활용하는지 보여줍니다. 필요에 따라 워커 로직을 확장하거나, 다른 서비스에서 상태 조회/표시용으로 재사용할 수 있습니다.
