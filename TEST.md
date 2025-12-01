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
    uvicorn app.main --host 0.0.0.0 --port 8000
```


### 테스트용 DNS scheduler 실행
```shell
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+":${PYTHONPATH}"}"
export DMS_SCHEDULER_URL="${DMS_SCHEDULER_URL:-http://127.0.0.1:9000}"

if [[ -z "${VIRTUAL_ENV:-}" && -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.venv/bin/activate"
fi

echo "Starting local scheduler stub on ${DMS_SCHEDULER_URL}" >&2
exec python3 -m uvicorn "cli.local_scheduler:app" --host 127.0.0.1 --port 9000
```


## 테스트용 curl

일단, 쿠버네티스에 테스트 파드를 띄우고, 쿼리를 날린다. `/help` 와 `/healthz` 를 제외한 모든 API 요청에는
`X-Operator-Token` 헤더가 필요하다.

```shell
kubectl exec -it frontend-test -- bash
```

### 쿼리 날리기
```shell
api_prefix="http://localhost:8000/api/v1"
token="${DMS_OPERATOR_TOKEN:-$(printenv DMS_OPERATOR_TOKEN)}"

curl -X GET "${api_prefix}/help" | jq
curl -X GET "${api_prefix}/healthz" | jq

# submit a sync task with name "cocoa.song"
curl -H "X-Operator-Token: ${token}" -X POST "${api_prefix}/services/sync/users/cocoa.song/tasks?input=123456"

# Submit a task with multiple query params (becomes task inputs)
curl -H "X-Operator-Token: ${token}" -X POST "${api_prefix}/services/sync/users/cocoa.song/tasks" \
  --data "" --get \
  --data-urlencode "src=/home/gpu1" \
  --data-urlencode "dst=/scratch"

# Fetch task status scoped to the user
task_id="1"
curl -H "X-Operator-Token: ${token}" "${api_prefix}/services/sync/tasks/${task_id}?user_id=cocoa.song" | jq

# List users who submitted sync tasks
curl -H "X-Operator-Token: ${token}" "${api_prefix}/services/sync/users"

# List user tasks
curl -H "X-Operator-Token: ${token}" "${api_prefix}/services/sync/users/cocoa.song/tasks"

# Cancel a task
curl -H "X-Operator-Token: ${token}" -X POST "${api_prefix}/services/sync/tasks/${task_id}/cancel" \
  --data "" --get --data-urlencode "user_id=cocoa.song" | jq

# Delete task metadata and logs (user-scoped)
curl -H "X-Operator-Token: ${token}" -X DELETE "${api_prefix}/services/sync/tasks/${task_id}?user_id=cocoa.song"

# Operator listing with token
curl "${api_prefix}/admin/tasks" -H "X-Operator-Token: ${token}"

# Operator cancellation of any task
curl -X POST "${api_prefix}/admin/tasks/${task_id}/cancel" -H "X-Operator-Token: ${token}"

# Operator cleanup of task metadata/logs
curl -X DELETE "${api_prefix}/admin/tasks/${task_id}" -H "X-Operator-Token: ${token}"
```

CLI 사용
```shell
api_prefix="http://localhost:8000/api/v1"
dms-frontend tasks list --service sync --user cocoa.song --api-base "${api_prefix}" | jq

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
