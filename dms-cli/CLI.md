# DMS CLI

## 개요

`dms`는 `dms-frontend` API를 interactive shell 형태로 호출하는 독립 배포형 CLI다.

- `dms`: 현재 사용자의 task를 다루는 user CLI
- `dms admin`: root + operator token 검증 후 진입하는 admin CLI
- `dms-kube`: 향후 kube 전용 기능을 위한 placeholder CLI

CLI는 HTTPS 기반 `dms-frontend`에 직접 요청하며, tab completion과 명령별 help를 제공한다.

## 설치

```bash
cd dms-cli
pip install -e .
```

설치 후 다음 셋 중 하나로 실행할 수 있다.

```bash
dms
dms-kube
python3 -m dms_cli
```

## 환경변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DMS_FRONTEND_URL` | `https://127.0.0.1:8000` | `dms-frontend` base URL |
| `DMS_FRONTEND_API_PREFIX` | `/api/v1` | API prefix |
| `DMS_CLI_CA_BUNDLE` | 없음 | 사설 CA 인증서 bundle 경로 |
| `DMS_CLI_INSECURE` | `true` | `true`면 TLS 검증 비활성화 |
| `DMS_CLI_TIMEOUT_SECONDS` | `10.0` | 요청 타임아웃(초) |

현재 설정값은 CLI 안에서 `env` 또는 `help env`로 확인할 수 있다.

## 보안 / 인증

### User CLI

- 토큰이 필요 없다.
- user scope API(`/services/...`)만 사용한다.
- `user_id`는 실제 CLI 실행 사용자 이름을 사용한다.

### Admin CLI

- root 계정이어야 한다.
- 시작 시 operator token을 숨김 입력받는다.
- 입력한 token은 `GET /api/v1/admin/auth/verify`로 검증된다.
- 검증이 성공해야 admin shell에 들어간다.

예시:

```bash
sudo dms admin
```

## 빠른 시작

```bash
export DMS_FRONTEND_URL="https://localhost:8000"
export DMS_CLI_INSECURE=true

dms
```

원샷 실행도 가능하다.

```bash
dms -c "list"
dms -c "run sync src=/home/gpu1/data dst=/pvs/archive options='--delete --direct'"
dms admin -c "list tasks"
dms-kube -c "hello scheduler"
```

## User CLI 명령

### 기본 명령 트리

```text
list
list mine
list service <service>

run <service> [key=value ...]

get <service> <task_id>

cancel mine
cancel service <service>
cancel task <service> <task_id>

delete mine
delete service <service>
delete task <service> <task_id>

health
env
help
```

### 예시

```bash
# 현재 사용자 기준 전체 task 조회
dms -c "list"

# sync task 실행
dms -c "run sync src=/home/gpu1/data dst=/pvs/archive options='--delete --direct'"

# rm task 실행
dms -c "run rm path=/home/gpu1/tmp/old-data"

# 특정 task 상태 확인
dms -c "get sync 10"

# 특정 service 범위 전체 취소
dms -c "cancel service sync"

# 특정 task metadata 삭제
dms -c "delete task sync 10"
```

## Admin CLI 명령

### 기본 명령 트리

```text
list tasks
list next-id
list service <service> tasks
list service <service> users

summary service <service>

cancel task <task_id>
cancel service <service>

delete task <task_id>
delete service <service>

health
env
help
```

### 예시

```bash
sudo dms admin -c "list tasks"
sudo dms admin -c "list service sync users"
sudo dms admin -c "summary service sync"
sudo dms admin -c "cancel task 10"
sudo dms admin -c "delete service rm"
```

## Kube CLI

현재는 placeholder만 있다.

```bash
dms-kube -c "hello"
dms-kube -c "hello scheduler"
```

## Help 와 자동완성

- `help`: 현재 셸의 명령 목록
- `help <command>`: usage, API route, 예제 표시
- `help env`: 주소/TLS/timeout 관련 환경변수 설명
- `Tab`: 정적 command/subcommand completion
- user CLI에서는 service 이름과 task id 동적 completion도 제공

예시:

```bash
dms
dms[alice]> help run
dms[alice]> run <TAB>
dms[alice]> get sync <TAB>
```

## HTTPS / SSL

운영 환경에서는 CA 검증을 유지하는 것을 권장한다.

```bash
export DMS_FRONTEND_URL="https://frontend.example:8000"
export DMS_CLI_CA_BUNDLE="/etc/ssl/certs/dms-ca.pem"
dms
```

로컬 self-signed 테스트만 다음처럼 사용한다.

```bash
export DMS_FRONTEND_URL="https://localhost:8000"
export DMS_CLI_INSECURE=true
dms
```

## 검증 명령

```bash
pytest tests/test_cli.py tests/test_api.py -q
python3 -m dms_cli --help
python3 -m dms_cli -c "help run"
python3 -m dms_cli.kube_main -c "hello scheduler"
```

루트 저장소 전체 `pytest -q`는 monorepo의 `app` package 충돌 때문에 적합하지 않다. frontend는 `pytest tests -q`, scheduler는 `cd dms-scheduler && pytest -q`로 분리 실행한다.
