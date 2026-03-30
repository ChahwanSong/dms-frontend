# Redis 인덱스 불일치 점검 스크립트 실행 가이드

`list brief`(user 전체) 결과와 `list service <service> brief`(service+user) 결과가 다를 때, `index:user:<user_id>` 와 `index:service:<service>:user:<user_id>` 간 불일치를 확인/복구하는 절차입니다.

## 1) 사전 준비

1. Python 환경을 활성화합니다.
2. Redis 접속 URL을 확인합니다.
   - 기본: `DMS_REDIS_WRITE_URL`
   - 미설정 시 스크립트 기본값: `redis://localhost:6379/0`
3. 점검 대상 `user_id`를 정합니다.

## 2) Dry-run 점검 (수정 없음)

### 특정 서비스만 점검

```bash
python scripts/redis_index_consistency_check.py \
  --user-id alice \
  --service sync \
  --redis-url "${DMS_REDIS_WRITE_URL}"
```

### 해당 유저의 모든 서비스 점검

```bash
python scripts/redis_index_consistency_check.py \
  --user-id alice \
  --redis-url "${DMS_REDIS_WRITE_URL}"
```

## 3) 결과 해석

출력 JSON 주요 필드:

- `user_index_count`: `index:user:<user_id>`에 있는 task id 개수
- `service_union_count`: `index:service:*:user:<user_id>`의 합집합 개수
- `missing_in_user_index`: service-user에는 있지만 user 인덱스에 없는 task id
- `extra_in_user_index`: user 인덱스에는 있지만 service-user 합집합에는 없는 task id

`missing_in_user_index_count > 0` 이면 `list brief`가 일부 task를 누락할 수 있습니다.

## 4) 복구 실행

아래 명령은 다음 동작을 수행합니다.

- `missing_in_user_index`를 `index:user:<user_id>`에 추가
- `extra_in_user_index`를 `index:user:<user_id>`에서 제거
- user 인덱스 TTL 재설정 (`--ttl-seconds`, 기본 90일)

```bash
python scripts/redis_index_consistency_check.py \
  --user-id alice \
  --redis-url "${DMS_REDIS_WRITE_URL}" \
  --repair
```

TTL을 명시하려면:

```bash
python scripts/redis_index_consistency_check.py \
  --user-id alice \
  --redis-url "${DMS_REDIS_WRITE_URL}" \
  --repair \
  --ttl-seconds 7776000
```

## 5) 복구 검증

동일 명령으로 dry-run 재실행하여 아래를 확인합니다.

- `missing_in_user_index_count == 0`
- `extra_in_user_index_count == 0`

## 6) 운영 권장 절차

1. 운영에서는 먼저 dry-run 결과를 저장합니다.
2. 사용량이 낮은 시간대에 `--repair`를 실행합니다.
3. 실행 후 동일 user/service 조합으로 API/CLI 결과를 재확인합니다.
4. 반복 발생 시 애플리케이션 로그에서 Redis write 에러(타임아웃/일시 장애)를 점검합니다.
