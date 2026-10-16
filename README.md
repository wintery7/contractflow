# ContractFlow AI

계약서 PDF를 업로드하면 LLM과 RAG로 핵심 정보를 근거와 함께 추출하고, 검토 업무와 처리 이력을 관리하는 백엔드 API.

> ⚠️ 분석 결과는 법률 자문이 아닌 **검토 보조 자료**입니다.
> ⚠️ 인증·권한이 **구현되어 있지 않습니다.** 로컬 단일 사용자 데모 전용입니다.

## 현재 진행 상태

| 마일스톤 | 상태 |
|---|---|
| M0 요구사항·설계 | 완료 — [docs/design](docs/design/) |
| M1 백엔드 기반 (문서 업로드/조회/삭제, 이력, 마이그레이션, 테스트) | 완료 (로컬 PostgreSQL로 검증) |
| M2 문서 분석 | 예정 |

## 빠른 시작

요구사항: Python 3.11.9, [uv](https://docs.astral.sh/uv/)

```bash
uv sync                              # 의존성 설치 (uv.lock 기준)
uv run python scripts/local_db.py start   # PostgreSQL 16 + pgvector (아래 참고)
uv run alembic upgrade head          # 스키마 생성
uv run uvicorn app.main:app --reload --no-access-log
```

### 환경변수

프로젝트 루트의 `.env`(git 제외) 또는 셸 환경변수로 설정한다. 모두 기본값이 있어 로컬 DB만 띄우면 바로 실행된다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://contractflow:change-me@localhost:5432/contractflow` | 앱 DB |
| `TEST_DATABASE_URL` | `…/contractflow_test` (같은 계정) | 통합 테스트 DB (셸 환경변수로만 읽음) |
| `POSTGRES_PASSWORD` | `change-me` | 로컬/Docker DB 최초 생성 시 비밀번호 (셸 환경변수) |
| `STORAGE_DIR` | `./var/uploads` | 업로드 원본 저장 위치 |
| `MAX_UPLOAD_BYTES` | `20971520` (20MB) | 업로드 최대 크기 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `OPENAI_API_KEY` | 없음 | M2부터 사용 (LLM·임베딩) |

### 데이터베이스 실행 방법

| 방법 | 명령 | 비고 |
|---|---|---|
| 로컬 (Docker 없이) | `uv run python scripts/local_db.py start / stop / status` | 개발 의존성 `pgserver`에 포함된 PostgreSQL 16 바이너리 사용, 데이터는 `var/pgdata`. 개발 전용 |
| Docker | `docker compose up -d db` | 배포 환경과 같은 공식 이미지(`pgvector/pgvector:pg16`) |

두 방법 모두 같은 계정·DB 이름·포트(5432)를 쓰므로 `DATABASE_URL`을 바꿀 필요가 없다.
앱 컨테이너화와 Docker 기반 검증은 M5에서 진행한다.

- Swagger UI: http://localhost:8000/docs
- 헬스체크: `GET /health/live`, `GET /health/ready`

## 테스트

```bash
uv run pytest                        # 전체 (통합 테스트는 contractflow_test DB 필요)
uv run pytest tests/unit             # DB 없이 실행 가능
uv run ruff check . && uv run ruff format --check .
```

통합 테스트는 실행 시 테스트 DB 스키마를 Alembic으로 `base → head` 재구성하고, 테스트마다 트랜잭션을 롤백해 서로 격리한다.

## 구조

```
app/
  api/         HTTP 계층 (라우터, 오류 변환, 본문 크기 제한)
  services/    유스케이스와 트랜잭션 경계
  domain/      순수 규칙 (상태 머신, 파일명 정규화)
  models/      SQLAlchemy ORM
  schemas/     Pydantic 요청/응답
  storage/     파일 저장소 인터페이스와 로컬 구현
  core/        설정, 로깅, 요청 ID
migrations/    Alembic
tests/         unit / integration
docs/design/   요구사항, 아키텍처, ERD, API 명세, 일정
```
