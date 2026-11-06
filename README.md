# ContractFlow AI

계약서 PDF를 업로드하면 LLM과 RAG로 핵심 정보를 근거와 함께 추출하고, 검토 업무와 처리 이력을 관리하는 백엔드 API.

> ⚠️ 분석 결과는 법률 자문이 아닌 **검토 보조 자료**입니다.
> ⚠️ 인증·권한이 **구현되어 있지 않습니다.** 로컬 단일 사용자 데모 전용입니다.

## 현재 진행 상태

| 마일스톤 | 상태 |
|---|---|
| M0 요구사항·설계 | 완료 — [docs/design](docs/design/) |
| M1 백엔드 기반 (문서 업로드/조회/삭제, 이력, 마이그레이션, 테스트) | 완료 |
| M2 문서 분석 (PDF 추출, 비동기 분석, 구조화 추출, 근거 검증) | 완료 — [구현 기록](docs/design/07-m2-analysis-notes.md) |
| M3 RAG | 예정 |

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
| `OPENAI_API_KEY` | 없음 | 분석에 필요. 없으면 분석 요청이 `503 LLM_NOT_CONFIGURED` |
| `LLM_MODEL` | `gpt-5.4-mini` | 구조화 추출 모델 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `60` / `2` | 호출 타임아웃, SDK 재시도 횟수(429·5xx·타임아웃) |
| `MAX_PAGES` / `MAX_ANALYSIS_CHARS` | `100` / `120000` | 분석 가능한 최대 페이지·글자 수 |
| `MIN_TEXT_CHARS` | `50` | 이보다 적으면 스캔 PDF로 보고 `NO_TEXT_LAYER` |

### 데이터베이스

PostgreSQL 16 이상과 같은 서버의 `<DB이름>`, `<DB이름>_test` 두 데이터베이스가 필요하다.
통합 테스트 DB는 `DATABASE_URL`의 DB 이름에 `_test`를 붙여 자동으로 정해지며, 이름이 `_test`로 끝나지 않으면 테스트가 실행을 거부한다(테스트가 스키마를 지웠다가 다시 만들기 때문).

| 방법 | 비고 |
|---|---|
| 설치형 PostgreSQL (현재 개발 환경: 18.6, Windows 서비스) | pgvector 별도 설치 필요 (M3) |
| `uv run python scripts/local_db.py start / stop / status` | 개발 의존성 `pgserver`의 PostgreSQL 16 + pgvector. 설치 없이 사용 가능, 개발 전용 |
| `docker compose up -d db` | 공식 이미지 `pgvector/pgvector:pg16`. 앱 컨테이너화는 M5 |

- Swagger UI: http://localhost:8000/docs
- 헬스체크: `GET /health/live`, `GET /health/ready`

## 테스트

```bash
uv run pytest                        # 단위 + 통합 (LLM은 Fake, 외부 호출 없음)
uv run pytest tests/unit             # DB 없이 실행 가능
uv run pytest -m live                # 실제 OpenAI 호출 (비용 발생, 기본 실행에서 제외)
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
  pipeline/    PDF 텍스트 추출, 정제, 품질 점검
  extraction/  구조화 추출 스키마·프롬프트·근거 검증
  llm/         LLM 공급자 인터페이스, OpenAI 구현, Fake
  workers/     분석 실행기 (BackgroundTasks)
  core/        설정, 로깅, 요청 ID
migrations/    Alembic
tests/         unit / integration
docs/design/   요구사항, 아키텍처, ERD, API 명세, 일정
```
