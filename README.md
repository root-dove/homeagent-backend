# homeagent-backend

HomeAgent의 모드 상태, 촬영 스케줄, 비전 분석과 알림 이벤트를 관리하는 FastAPI 백엔드입니다.

## 현재 구현 범위

- FastAPI 애플리케이션과 버전이 명시된 `/api/v1` 경로
- 애플리케이션 및 PostgreSQL 상태 확인 API
- SQLAlchemy 2와 psycopg 3 연결 기반
- Alembic 마이그레이션 기준선
- Docker Compose 기반 API·PostgreSQL 개발 환경
- pytest와 Ruff 검증 환경

청결 모드와 카메라 장치 API는 다음 개발 단계에서 추가합니다. 전체 요구사항과 진행 상황은 [PROJECT_PLAN.md](./PROJECT_PLAN.md)를 참고하세요.

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
| `POSTGRES_DB` | Compose PostgreSQL DB 이름 | `homeagent` |
| `POSTGRES_USER` | Compose PostgreSQL 사용자 | `homeagent` |
| `POSTGRES_PASSWORD` | Compose PostgreSQL 비밀번호 | 로컬에서 변경 권장 |

`.env` 파일과 실제 운영 비밀값은 Git에 커밋하지 않습니다.
