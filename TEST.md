# DMS Frontend 개발 테스트  

## 컨테이너 실행
### 테스트 container 실행 w/ volume mount

```shell
kubectl run frontend-test \
  --rm -it \
  --restart=Never \
  --image=rts2411:5000/dms-dsync:latest \
  --overrides='
{
  "apiVersion": "v1",
  "spec": {
    "hostNetwork": true,
    "dnsPolicy": "ClusterFirstWithHostNet",
    "nodeSelector": {
      "kubernetes.io/hostname": "ion2407"
    },
    "volumes": [
      {
        "name": "host-dsync",
        "hostPath": {
          "path": "/home/gpu1/cocoa.song/workspace/dms/dsync",
          "type": "Directory"
        }
      }
    ],
    "containers": [
      {
        "name": "frontend-test",
        "image": "rts2411:5000/dms-dsync:latest",
        "stdin": true,
        "tty": true,
        "command": ["sh"],
        "volumeMounts": [
          {
            "name": "host-dsync",
            "mountPath": "/dsync"
          }
        ]
      }
    ]
  }
}'
```

### 원격에서 연결

```shell
kubectl exec -it frontend-test -- bash
```



## 서비스 실행 

### DMS frontend 서비스 실행
```shell
set -eux pipefail;\
    export DMS_REDIS_WRITE_URL="redis://127.0.0.1:6379";\
    export DMS_REDIS_READ_URL="redis://127.0.0.1:6379";\
    export DMS_SCHEDULER_BASE_URL="http://127.0.0.1:9000";\
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile /dms/ssl-cert/key.pem --ssl-certfile /dms/ssl-cert/cert.pem
```


### 테스트용 DMS scheduler 실행
```shell
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+":${PYTHONPATH}"}"

if [[ -z "${VIRTUAL_ENV:-}" && -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.venv/bin/activate"
fi

echo "Starting local scheduler stub on http://127.0.0.1:9000" >&2
exec python3 -m uvicorn "app.dev.local_scheduler_stub:app" --host 127.0.0.1 --port 9000
```


## 테스트용 curl

일단, 쿠버네티스에 테스트 파드를 띄우고, 쿼리를 날린다. `/admin` API 요청에는
`X-Operator-Token` 헤더가 필요하고, `user_id` 로 스코프가 정해지는 `/services` 요청은 public 이다.

```shell
kubectl exec -it frontend-test -- bash
```

### 쿼리 날리기
```shell
api_prefix="https://localhost:8000/api/v1"
token="${DMS_OPERATOR_TOKEN:-$(printenv DMS_OPERATOR_TOKEN)}"

curl -k -X GET "${api_prefix}/help" | jq
curl -k -X GET "${api_prefix}/healthz" | jq

# submit a sync task with name "cocoa.song"
curl -k -X POST "${api_prefix}/services/sync/users/cocoa.song/tasks?input=123456"

# Submit a task with multiple query params (becomes task inputs)
curl -k -X POST "${api_prefix}/services/sync/users/cocoa.song/tasks" \
  --data "" --get \
  --data-urlencode "src=/home/gpu1" \
  --data-urlencode "dst=/scratch"

# Fetch task status scoped to the user
task_id="1"
curl -k "${api_prefix}/services/sync/tasks/${task_id}?user_id=cocoa.song" | jq

# List users who submitted sync tasks
curl -k -H "X-Operator-Token: ${token}" "${api_prefix}/admin/services/sync/users"

# List user tasks
curl -k "${api_prefix}/services/sync/users/cocoa.song/tasks"

# Cancel a task
curl -k -X POST "${api_prefix}/services/sync/tasks/${task_id}/cancel" \
  --data "" --get --data-urlencode "user_id=cocoa.song" | jq

# Delete task metadata and logs (user-scoped)
curl -k -X DELETE "${api_prefix}/services/sync/tasks/${task_id}?user_id=cocoa.song"

# User-level list/cancel/delete
curl -k "${api_prefix}/services/users/cocoa.song/tasks" | jq
curl -k -X POST "${api_prefix}/services/users/cocoa.song/tasks/cancel" | jq
curl -k -X DELETE "${api_prefix}/services/users/cocoa.song/tasks" | jq

# Service + user scoped cancel/delete
curl -k -X POST "${api_prefix}/services/sync/users/cocoa.song/tasks/cancel" | jq
curl -k -X DELETE "${api_prefix}/services/sync/users/cocoa.song/tasks" | jq

# Operator listing with token
curl -k "${api_prefix}/admin/tasks" -H "X-Operator-Token: ${token}"

# Peek next task ID cursor
curl -k "${api_prefix}/admin/tasks/next-id" -H "X-Operator-Token: ${token}" | jq

# Service-level list/cancel/delete
curl -k "${api_prefix}/admin/services/sync/tasks" -H "X-Operator-Token: ${token}" | jq
curl -k -X POST "${api_prefix}/admin/services/sync/tasks/cancel" -H "X-Operator-Token: ${token}" | jq
curl -k -X DELETE "${api_prefix}/admin/services/sync/tasks" -H "X-Operator-Token: ${token}" | jq

# Service-level compact status summary
curl -k "${api_prefix}/admin/services/sync/tasks/summary" -H "X-Operator-Token: ${token}" | jq

# Operator cancellation of any task
curl -k -X POST "${api_prefix}/admin/tasks/${task_id}/cancel" -H "X-Operator-Token: ${token}"

# Operator cleanup of task metadata/logs
curl -k -X DELETE "${api_prefix}/admin/tasks/${task_id}" -H "X-Operator-Token: ${token}"

# NOTE: /admin/tasks/{task_id} delete는 취소 요청을 비동기로 먼저 전달한 뒤,
# task metadata/log 를 즉시 삭제한다. scheduler 쪽 job/pod 정리 완료까지 기다리지는 않는다.
```

### redis 직접 접근
```shell
[root@ion2410 ~]# kubectl run redis-test --rm -it --image=rts2411:5000/redis:7.2-alpine -- sh

# key 값 스캔
redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 scan 0

# 모든 value 출력
redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 scan 0 | \
while read key; do
  if [[ "$key" != 0 && "$key" != 1 && -n "$key" ]]; then
    echo ">>> $key"
    redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 get "$key"
  fi
done

# TTL + Type + Value 보기

for key in $(redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 --scan); do
  type=$(redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 type "$key")
  ttl=$(redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 ttl "$key")
  echo "===== $key ====="
  echo "Type: $type"
  echo "TTL : $ttl"

  case "$type" in
    string) redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 get "$key" ;;
    hash)   redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 hgetall "$key" ;;
    list)   redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 lrange "$key" 0 -1 ;;
    set)    redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 smembers "$key" ;;
    zset)   redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 zrange "$key" 0 -1 WITHSCORES ;;
  esac

  echo
done




# 모든 key-value 데이터 제거
redis-cli -h haproxy-redis.dms-redis.svc.cluster.local -p 6379 flushall
```
