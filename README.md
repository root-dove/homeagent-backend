# homeagent-backend

HomeAgent의 모드 상태, 촬영 스케줄, 비전 분석과 알림 이벤트를 관리하는 FastAPI 백엔드입니다.

## 현재 구현 범위

- FastAPI 애플리케이션과 버전이 명시된 `/api/v1` 경로
- 애플리케이션 및 PostgreSQL 상태 확인 API
- SQLAlchemy 2와 psycopg 3 연결 기반
- Alembic 마이그레이션과 공통 모드·상태 이력 모델
- 모드 등록·조회 및 멱등 활성·비활성 API
- 청결 모드 상태 전이와 청소 완료 검사 API
- 침대·책상·바닥 등 영역별 청결 분석 결과 스키마
- PostgreSQL 기반 영속 스케줄러와 실행 작업 큐
- 카메라 장치 등록·API 키 인증·heartbeat와 연결 상태 계산
- 임대 기반 촬영 작업 수령·완료·실패·재시도 API
- JPEG 검증·크기 제한·비공개 볼륨을 적용한 멱등 사진 업로드 API
- Asia/Seoul 기본 방해 금지 및 모드별 재정의 정책
- Docker Compose 기반 API·PostgreSQL 개발 환경
- pytest와 Ruff 검증 환경

실제 카메라 촬영과 비전 모델 연결은 다음 개발 단계에서 추가합니다. 전체 요구사항과 진행 상황은 [PROJECT_PLAN.md](./PROJECT_PLAN.md)를 참고하세요.

## 빠른 실행

Docker Desktop이 실행된 상태에서 다음 명령을 사용합니다.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

확인 주소:

- API 문서: <http://localhost:8000/docs>
- 생존 상태: <http://localhost:8000/api/v1/health/live>
- 준비 상태: <http://localhost:8000/api/v1/health>

## 모드 API

모드는 확장 가능한 `instance_key`로 식별합니다. 초기 청결 모드는 다음 요청으로 등록합니다.

```powershell
$body = @{
    instance_key = "cleanliness"
    mode_type = "cleanliness"
    name = "청결 모드"
    config = @{ interval_minutes = 30 }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/modes" `
    -Method Post -ContentType "application/json" -Body $body
```

주요 경로:

- `GET /api/v1/modes`: 전체 모드 조회
- `GET /api/v1/modes/{instance_key}`: 단일 모드 조회
- `POST /api/v1/modes/{instance_key}/enable`: 모드 활성화
- `POST /api/v1/modes/{instance_key}/disable`: 모드 비활성화
- `POST /api/v1/modes/{instance_key}/analysis/start`: 정기 또는 재시도 분석 시작
- `POST /api/v1/modes/{instance_key}/analysis/result`: 구조화된 분석 결과 반영
- `POST /api/v1/modes/{instance_key}/cleaning-complete`: 청소 완료 후 검증 시작

활성·비활성 요청은 멱등하게 처리됩니다. 비활성화해도 `DIRTY` 같은 내부 실행 상태는 보존되며, 비활성 상태에서 남아 있던 다음 실행 예약만 제거합니다.

현재 `analysis/result`는 실제 비전 제공자를 연결하기 전에 가짜 결과로 전체 상태 흐름을 검증하기 위한 입력점이기도 합니다. 결과에는 전체 판정뿐 아니라 영역별 점수, 판정과 문제 목록이 필요합니다. 실제 제공자 연결 후에도 같은 스키마를 사용합니다.

## 스케줄러와 방해 금지

스케줄러는 `next_run_at`이 지난 활성 모드를 PostgreSQL 행 잠금으로 가져옵니다. 상태 전이와 `mode_runs` 작업 생성을 한 트랜잭션으로 저장하므로 서버가 재시작돼도 대기 작업이 유지되고 여러 스케줄러가 같은 예약을 중복 생성하지 않습니다.

기본 방해 금지는 `Asia/Seoul` 기준 23:00~07:00입니다. 해당 시간에는 내부 상태를 변경하거나 작업을 만들지 않고 종료 시각으로 `next_run_at`만 미룹니다. 모드의 `config.quiet_hours`에서 시간대를 재정의하거나 `enabled: false`로 기본 정책을 끌 수 있습니다.

현재는 촬영 작업 소비자가 없으므로 `SCHEDULER_ENABLED=false`가 기본입니다. 카메라 작업 관리자를 연결한 뒤 `true`로 변경합니다.

## 카메라 장치 API

장치 등록은 서버 운영자가 설정한 `DEVICE_REGISTRATION_TOKEN`을 사용합니다. 등록 성공 시 장치 API 키가 한 번만 반환되므로 라즈베리파이의 권한이 제한된 설정 파일에 저장해야 합니다. 서버에는 원문 키가 아닌 PBKDF2-SHA256 해시만 저장됩니다.

주요 경로:

- `POST /api/v1/devices/register`: 장치 등록 및 최초 API 키 발급
- `GET /api/v1/devices`: 장치 목록과 online/offline 상태 조회
- `POST /api/v1/devices/heartbeat`: 에이전트·카메라 상태 보고
- `POST /api/v1/devices/commands/claim`: queued 촬영 작업을 임대 방식으로 수령
- `POST /api/v1/devices/commands/{run_id}/capture`: JPEG 업로드 및 촬영 작업 완료
- `POST /api/v1/devices/commands/{run_id}/complete`: 저장된 capture가 있는 작업의 완료 재확인
- `POST /api/v1/devices/commands/{run_id}/fail`: 실패 보고 및 재시도 요청

등록·목록 API에는 `X-HomeAgent-Registration-Token`, 장치 API에는 `X-HomeAgent-Device-Key` 헤더를 사용합니다. 작업을 수령하면 설정된 임대 시간 안에 완료 또는 실패를 보고해야 하며, 만료된 작업은 최대 시도 횟수까지 다시 대기열에 들어갑니다. 완료·최종 실패 재호출은 작업 ID 기준으로 멱등 처리됩니다.

## 사진 업로드와 보존

촬영 작업은 multipart 형식으로 `captured_at`과 `image/jpeg` 파일을 업로드합니다. 서버는 원본 파일명을 사용하지 않고 capture UUID로 저장하며, 다음 검증을 모두 통과한 경우에만 DB 기록과 작업 완료를 커밋합니다.

- 실제 JPEG 디코딩 검증
- 기본 최소 해상도 1280×720
- 기본 최대 5천만 픽셀과 15MB 제한
- 시간대가 포함된 촬영 시각 및 허용 범위 검사
- 작업을 임대한 장치와 임대 만료 시각 확인

같은 `run_id`를 다시 업로드하면 기존 capture를 반환하므로 파일을 중복 저장하지 않습니다. 파일은 `/service/data/captures`의 Docker 비공개 볼륨에 저장되고 API 응답에는 내부 경로가 노출되지 않습니다. 기본 만료 시각은 업로드 후 7일이며, 실제 만료 파일 삭제 작업은 다음 단계에서 구현합니다.

사진이 없는 촬영 작업은 `/complete`만 호출해 완료할 수 없습니다. 업로드와 DB 저장이 성공해야 작업이 `completed`로 바뀝니다.

종료:

```powershell
docker compose down
```

데이터까지 삭제해야 하는 경우에만 `docker compose down -v`를 사용합니다.

## 로컬 Python 실행

Python 3.12 이상과 실행 중인 PostgreSQL이 필요합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## 검증

```powershell
ruff check .
ruff format --check .
mypy
pytest
```

## 환경 변수

| 변수 | 설명 | 기본 개발값 |
|---|---|---|
| `APP_ENV` | 실행 환경 | `development` |
| `LOG_LEVEL` | 로그 수준 | `INFO` |
| `DATABASE_URL` | SQLAlchemy PostgreSQL 연결 주소 | `.env.example` 참고 |
| `DATABASE_ECHO` | SQL 쿼리 로그 출력 여부 | `false` |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | DB 연결 확인 제한 시간 | `3` |
| `SCHEDULER_ENABLED` | 백그라운드 스케줄러 실행 여부 | `false` |
| `SCHEDULER_POLL_INTERVAL_SECONDS` | 실행 대상 조회 간격(초) | `10` |
| `SCHEDULER_BATCH_SIZE` | 한 번에 가져올 최대 모드 수 | `10` |
| `QUIET_HOURS_ENABLED` | 전역 방해 금지 사용 여부 | `true` |
| `QUIET_HOURS_TIMEZONE` | 방해 금지 기준 시간대 | `Asia/Seoul` |
| `QUIET_HOURS_START` | 방해 금지 시작 | `23:00` |
| `QUIET_HOURS_END` | 방해 금지 종료 | `07:00` |
| `DEVICE_REGISTRATION_TOKEN` | 장치 등록·관리용 비밀 토큰 | 반드시 별도 설정 |
| `DEVICE_OFFLINE_AFTER_SECONDS` | heartbeat 이후 offline 판정 시간(초) | `90` |
| `DEVICE_COMMAND_LEASE_SECONDS` | 수령한 작업의 처리 임대 시간(초) | `120` |
| `DEVICE_COMMAND_MAX_ATTEMPTS` | 만료·실패 작업의 최대 시도 횟수 | `3` |
| `CAPTURE_STORAGE_DIR` | 원본 사진 비공개 저장 경로 | `./data/captures` |
| `CAPTURE_MAX_UPLOAD_BYTES` | 사진 한 장 최대 크기 | `15728640` |
| `CAPTURE_RETENTION_DAYS` | 사진 만료 시각 계산 일수 | `7` |
| `CAPTURE_MIN_WIDTH` | 허용할 최소 너비 | `1280` |
| `CAPTURE_MIN_HEIGHT` | 허용할 최소 높이 | `720` |
| `CAPTURE_MAX_PIXELS` | 이미지 폭×높이 최대값 | `50000000` |
| `POSTGRES_DB` | Compose PostgreSQL DB 이름 | `homeagent` |
| `POSTGRES_USER` | Compose PostgreSQL 사용자 | `homeagent` |
| `POSTGRES_PASSWORD` | Compose PostgreSQL 비밀번호 | 로컬에서 변경 권장 |

`.env` 파일과 실제 운영 비밀값은 Git에 커밋하지 않습니다.
