# DMS CLI 설계 및 구현 플랜

## 1. 목표

`dms-frontend` REST API를 사람이 직접 다루기 쉬운 계층형 CLI로 감싸고, 사용자 전용 셸과 admin 전용 셸을 분리한다.

- `dms`: 현재 CLI 실행 사용자의 user scope를 사용하는 user CLI
- `dms admin`: root + operator token 검증이 필요한 admin CLI
- `dms kube`: 향후 kube 전용 CLI 확장을 위한 placeholder CLI

## 2. 설계 요약

### 2.1 모드 구조

```text
dms
  list [mine | service <service>]
  run <service> [key=value ...]
  get <service> <task_id>
  cancel [mine | service <service> | task <service> <task_id>]
  delete [mine | service <service> | task <service> <task_id>]
  health
  env
  help

dms admin
  list [tasks | next-id | service <service> tasks | service <service> users]
  summary service <service>
  cancel [task <task_id> | service <service>]
  delete [task <task_id> | service <service>]
  health
  env
  help

dms kube
  hello [name]
  env
  help
```

### 2.2 인증 모델

- user CLI는 토큰 없이 `/services` 계층 API를 호출한다.
- admin CLI는 먼저 로컬에서 `root(uid 0)` 여부를 확인한다.
- root 확인 후 operator token을 숨김 입력받는다.
- 입력받은 토큰은 `dms-frontend`의 `GET /api/v1/admin/auth/verify`로 검증한다.
- 검증 성공 시에만 admin 셸로 진입한다.
- 토큰은 메모리에만 유지하고 파일로 저장하지 않는다.

### 2.3 user_id 결정

- user CLI의 `user_id`는 실제 CLI 실행 사용자를 기준으로 잡는다.
- `sudo` 환경에서는 `SUDO_USER`를 우선 사용하고, 아니면 현재 uid의 username을 사용한다.

### 2.4 HTTPS / 배포

- frontend 주소는 환경변수 `DMS_FRONTEND_URL`로 주입한다.
- 기본 API prefix는 `DMS_FRONTEND_API_PREFIX=/api/v1`
- 사설 CA 환경을 위해 `DMS_CLI_CA_BUNDLE` 지원
- 테스트/개발 환경을 위해 `DMS_CLI_INSECURE=true` 지원
- 패키지 설치 시 `dms` console script가 생성되도록 `pyproject.toml`에 entrypoint 추가
- `python3 -m dms_cli` 실행도 가능하게 구성 (독립 패키지: `dms-cli/`)

### 2.5 자동완성

- 정적 자동완성: `cmd.Cmd` + `readline` 기반 tab completion
- 동적 자동완성:
  - user shell에서 service 후보 자동완성
  - user shell에서 현재 user 기준 task_id 자동완성
  - admin shell은 우선 정적 completion 중심

### 2.6 Help 설계

- 모든 셸에서 `help`, `help <command>`, `env`, `help env` 제공
- 각 명령어 help에는 다음을 포함
  - usage
  - 매핑되는 API route
  - CLI 예제
  - scheduler 사용 예시를 반영한 parameter 예제

## 3. 구현 순서

1. 기존 `/services`, `/admin` API inventory 확인
2. admin token 검증 전용 endpoint 추가
3. CLI 테스트 추가
4. CLI client/config/shell 구현
5. console script 등록
6. smoke test 및 self review
7. 설치/사용 문서 작성

## 4. 요구사항 반영 체크리스트

| 요구사항 | 반영 방식 | 상태 |
| --- | --- | --- |
| `dms` user CLI 진입 | `dms_cli.main` 기본 모드 | 완료 |
| `dms admin` admin CLI 진입 | argparse 모드 + admin shell | 완료 |
| admin은 root + token 필요 | `is_root_user()` + token prompt | 완료 |
| token은 frontend로부터 인증 | `/api/v1/admin/auth/verify` 추가 | 완료 |
| `dms kube` placeholder | `KubeShell.hello` 구현 | 완료 |
| user_id는 실제 CLI 사용자 | `resolve_cli_user_id()` | 완료 |
| help 필수 | `help`, `help <command>`, `env` | 완료 |
| API hierarchy 반영 | user/admin shell command tree 분리 | 완료 |
| user `/services` 명령 구현 | list/run/get/cancel/delete | 완료 |
| admin `/admin` 명령 구현 | list/summary/cancel/delete | 완료 |
| 정적 tab 자동완성 | `readline` + `complete_*` | 완료 |
| 동적 자동완성 선택 구현 | user service/task_id completion | 완료 |
| scheduler 참고 예제 | `run` help 예제 반영 | 완료 |
| frontend 주소 env 제공 | `DMS_FRONTEND_URL`, `help env` | 완료 |
| 여러 노드 배포 용이성 | console script + module execution | 완료 |
| 단계별 테스트/검증 | pytest + smoke test + review 로그 | 완료 |
| CLI 계획 문서화 | 이 문서 | 완료 |
| 설치/사용 문서화 | `CLI.md` | 완료 |

## 5. 테스트 및 검증 프로세스

### 5.1 추가한 자동 테스트

- `tests/test_api.py`
  - `GET /api/v1/admin/auth/verify` 성공/실패 검증
- `tests/test_cli.py`
  - user shell command routing
  - help/env 출력
  - 동적 completion
  - admin shell summary routing
  - kube placeholder
  - TLS CA bundle 설정
  - `dms admin` root/token 검증 흐름
  - `dms -c ...` 기본 user mode 동작

### 5.2 실행한 검증 명령

```bash
pytest tests/test_cli.py tests/test_api.py -q
pytest tests -q
python3 -m dms_cli --help
python3 -m dms_cli -c "help run"
python3 -m dms_cli kube -c "hello scheduler"
```

### 5.3 저장소 구조상 주의사항

- 루트에서 `pytest -q`를 바로 실행하면 `app` 패키지 이름이 `dms-scheduler/app`와 충돌해서 scheduler 테스트 수집이 깨진다.
- 따라서 현재 저장소는 아래처럼 분리 실행해야 한다.

```bash
pytest tests -q
cd dms-scheduler && pytest -q
```

- `dms-scheduler` 독립 실행 테스트는 이번 변경과 무관하게 기존 실패 1건이 있었다.
  - `tests/test_rm_handler.py::test_execute_logs_ignored_options_before_path_validation[asyncio]`

## 6. 리뷰 및 개선 프로세스

실제 구현 후 다음 self review를 수행했다.

1. CLI unit/integration test 통과 여부 확인
2. `python3 -m dms_cli` smoke test 수행
3. help 출력/argument parser 동작 재검토
4. 문서와 실제 명령 이름 불일치 여부 점검

이 과정에서 수정한 항목:

- `dms -c "..."`가 실패하던 parser 기본값 버그 수정
  - 원인: 기본 모드를 `user`로 두고 `argparse choices`에는 `user`를 포함하지 않았음
  - 조치: `choices=("user", "admin", "kube")`로 수정하고 테스트 추가

## 7. 후속 개선 후보

- admin shell에도 task id/service name 동적 completion 추가
- JSON 출력 외에 table 출력 옵션 추가
- non-interactive automation용 `--token-stdin` 또는 secure file descriptor 입력 지원
- bash/zsh shell completion script 생성 기능 추가
