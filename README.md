# ContractFlow AI

계약서 PDF를 업로드하면 **원문 근거가 붙은 핵심 정보 추출**, **근거 기반 질의응답(RAG)**, **AI 제안 → 사용자 승인 검토 업무 관리**와 처리 이력을 제공하는 AI 백엔드 API.

> ⚠️ 분석 결과는 법률 자문이 아닌 **검토 보조 자료**입니다.
> ⚠️ 인증·권한이 **구현되어 있지 않습니다.** 로컬 단일 사용자 데모 전용입니다.

## 핵심 특징

| | 무엇을 | 어떻게 |
|---|---|---|
| 근거 검증 추출 | 계약 제목·당사자·기간·금액·자동 갱신·해지·위약금·지급·비밀유지 + 검토 필요 항목 | 필드마다 `FOUND / NOT_FOUND / AMBIGUOUS`, 원문 인용·페이지. 서버가 인용문을 원문과 대조해 `VERIFIED / UNVERIFIED` 표시. 상태-값 모순(환각 패턴)은 스키마에서 거절 후 1회 교정 |
| 근거 기반 질의응답 | "중도 해지 조건은?" 같은 질문에 답과 근거 청크·페이지·유사도 반환 | 유사도가 임계값 미만이면 LLM 미호출, 모델이 실제 발췌문을 인용하지 않으면 답 미반환 (`INSUFFICIENT_EVIDENCE`) |
| 비동기 분석 | 업로드 → 분석 요청 즉시 202 → 상태 폴링 | 상태의 정본은 DB, 단계(stage)별 기록, 부분 유니크 인덱스로 중복 실행 방지, 재시작 시 중단 작업 정리 |
| 검토 업무 | AI 검토 항목을 사용자가 승인해 업무화, 상태·담당자·기한 관리 | AI는 제안만(자동 생성 없음), 중복 승인 DB 제약, `version` 낙관적 잠금, 필드별 변경 이력 |
| 운영 | 감사 이벤트, LLM 호출 메타데이터, 요청 ID, 고아 파일 정리 | 원문·질문·API 키는 로그에 남기지 않음 |

## 아키텍처

```mermaid
flowchart LR
    C[Client / Swagger UI] -->|REST /api/v1| API
    subgraph APP[FastAPI 모듈형 모놀리스]
        API[Router<br/>스키마·오류 변환] --> SVC[Service<br/>트랜잭션·상태 전이·감사]
        SVC --> RUN[Analysis Runner<br/>BackgroundTasks]
        RUN --> PIPE[추출·정제·청킹·임베딩·색인]
        RUN --> EXT[구조화 추출 + 인용 검증]
        SVC --> QA[RAG 질의응답<br/>검색·답변·인용 검증]
        PIPE & EXT & QA --> LLM[[LLMClient / Embedder<br/>프로토콜 + Fake]]
    end
    SVC & PIPE & QA --> DB[(PostgreSQL + pgvector)]
    SVC & PIPE --> FS[/업로드 파일 저장소/]
    LLM --> OAI[(OpenAI API)]
```

| 계층 | 책임 |
|---|---|
| `api/` | HTTP ↔ 스키마 변환, 공통 오류 형식, 본문 크기 제한 미들웨어 |
| `services/` | 유스케이스 단위 트랜잭션, 상태 전이, 감사 이벤트 (HTTP를 모름) |
| `domain/` | 상태 머신·파일명 정규화 등 순수 규칙 |
| `pipeline/`, `extraction/`, `rag/` | 입력→출력이 명확한 처리 단계 |
| `llm/` | 공급자 추상화(OpenAI, Fake), 구조화 출력 공통 흐름 |
| `workers/` | 분석 실행 오케스트레이션 |

## 기술 스택과 선택 이유

| 영역 | 선택 | 이유 (대안) |
|---|---|---|
| API | FastAPI + Pydantic | 스키마 기반 검증·OpenAPI 자동 생성 (Django REST, Flask) |
| DB | PostgreSQL + SQLAlchemy 2 + Alembic | 제약조건·부분 인덱스·JSONB, 마이그레이션 이력 |
| 벡터 검색 | **pgvector** | 문서 삭제 시 청크·벡터를 같은 트랜잭션에서 삭제. 문서 범위 검색이라 ANN 없이 정확 검색 (Chroma, Qdrant) |
| LLM | OpenAI (`gpt-5.4-mini`, `text-embedding-3-small`) | strict JSON 스키마 구조화 출력. 프로토콜 뒤에 있어 교체 가능 |
| 오케스트레이션 | 직접 구현 | 페이지 보존·인용 검증 등 핵심 로직을 직접 통제 (LangChain) |
| 비동기 | DB 상태 + BackgroundTasks | 현재 규모에 충분. 다음 단계는 `SKIP LOCKED` 워커 (Celery + Redis) |

자세한 비교: [docs/design/02-architecture.md](docs/design/02-architecture.md)

## 빠른 시작

요구사항: Python 3.11.9, [uv](https://docs.astral.sh/uv/)

```bash
uv sync                                        # 의존성 설치 (uv.lock 기준)
uv run python scripts/local_db.py start        # PostgreSQL 16 + pgvector (포트 5433, 설치 불필요)
uv run alembic upgrade head                    # 스키마 생성
echo "OPENAI_API_KEY=sk-..." >> .env           # 분석·질의응답에 필요
uv run uvicorn app.main:app --reload --no-access-log
```

- Swagger UI: http://localhost:8000/docs · 헬스체크: `/health/live`, `/health/ready`
- 시연 순서: [docs/portfolio/demo-scenario.md](docs/portfolio/demo-scenario.md)

**Docker로 실행** (Docker Desktop 필요)

```bash
docker compose up --build        # 앱 :8000, DB :5434 (pgvector/pgvector:pg16)
```

### 환경변수

`.env`(git 제외) 또는 셸 환경변수. 모두 기본값이 있다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://contractflow:change-me@localhost:5433/contractflow` | 앱 DB. 통합 테스트는 DB 이름 + `_test`를 자동 사용 |
| `OPENAI_API_KEY` | 없음 | 없으면 분석·질의응답 요청이 `503 LLM_NOT_CONFIGURED` |
| `LLM_MODEL` / `EMBEDDING_MODEL` | `gpt-5.4-mini` / `text-embedding-3-small` | 임베딩 차원(1536)은 DB 컬럼과 같아야 함 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `60` / `2` | SDK 재시도(429·5xx·타임아웃) |
| `CHUNK_MAX_CHARS` / `CHUNK_OVERLAP_CHARS` | `500` / `100` | 청킹 설정 |
| `QA_TOP_K` / `QA_MIN_SCORE` | `5` / `0.25` | 검색 개수, LLM 호출 전 근거 부족 판단 임계값 |
| `MAX_UPLOAD_BYTES` / `MAX_PAGES` / `MAX_ANALYSIS_CHARS` | 20MB / `100` / `120000` | 처리 한도 |
| `MIN_TEXT_CHARS` | `50` | 이보다 적으면 스캔 PDF로 보고 `NO_TEXT_LAYER` |
| `STORAGE_DIR` | `./var/uploads` | 업로드 원본 저장 위치 |
| `LOG_LEVEL` | `INFO` | |

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/documents` | PDF 업로드 (매직 바이트·크기 검증, 중복 409) |
| GET | `/api/v1/documents` | 목록 (상태 필터, 페이지네이션) |
| GET / DELETE | `/api/v1/documents/{id}` | 상세 / 삭제 (원문 페이지·청크·파일 즉시 삭제) |
| GET | `/api/v1/documents/{id}/history` | 처리 이력 (업로드·분석·업무) |
| POST | `/api/v1/documents/{id}/analyses` | 분석 시작 → 202 (같은 조건 성공 결과가 있으면 200 재사용, `force`로 재분석) |
| GET | `/api/v1/documents/{id}/analyses`, `/analyses/latest` | 분석 이력, 최신 분석 |
| GET | `/api/v1/analyses/{analysis_id}` | 분석 상태·결과 폴링 |
| POST | `/api/v1/documents/{id}/questions` | 근거 기반 질의응답 |
| POST / GET | `/api/v1/documents/{id}/tasks` | 업무 생성(직접 / AI 제안 승인) / 목록 |
| GET / PATCH | `/api/v1/tasks/{task_id}` | 업무 상세 / 수정 (`version` 필수) |
| GET | `/api/v1/tasks/{task_id}/history` | 업무 변경 이력 |

오류는 모두 `{"error": {"code", "message", "details", "request_id"}}` 형식. 상세: [docs/design/04-api-spec.md](docs/design/04-api-spec.md)

## 테스트와 품질

```bash
uv run pytest                    # 단위 + 통합 (실제 PostgreSQL, Fake LLM — 외부 호출 없음)
uv run pytest -m live            # 실제 OpenAI 호출 (비용 발생, 기본 제외)
uv run ruff check . && uv run ruff format --check .
uv run python -m evaluation.run_retrieval_eval   # 검색 품질 실험 (OpenAI 임베딩 사용)
```

- **236개 테스트 통과** (2026-11-09, 로컬 PostgreSQL 16 + pgvector 0.6.2)
- 통합 테스트는 Alembic으로 스키마를 만들고, 테스트마다 트랜잭션을 롤백해 격리. DB 이름이 `_test`로 끝나지 않으면 실행 거부
- 실패 시나리오(LLM 타임아웃, 잘못된 JSON, 근거 없는 인용, 스캔 PDF, 동시 수정 충돌 등)를 Fake로 재현
- CI: [.github/workflows/ci.yml](.github/workflows/ci.yml) — 린트, 마이그레이션 차이 검사, 테스트(pgvector 서비스 컨테이너), Docker 빌드·스모크 테스트

### 검색·답변 품질 평가

가상 계약서 4건, 질문 40개(사실·위치·복수 조건·비슷한 조항·문서에 없음·모호)로 청크 크기 → 겹침 → top-k → 검색 방식(벡터/BM25/하이브리드)을 한 번에 하나씩 비교한다. 방법과 결과: [docs/evaluation.md](docs/evaluation.md)

## 문서

| 문서 | 내용 |
|---|---|
| [01 요구사항](docs/design/01-requirements.md) · [02 아키텍처](docs/design/02-architecture.md) · [03 ERD](docs/design/03-erd.md) · [04 API 명세](docs/design/04-api-spec.md) | M0 설계 (구현 후 변경 사항 포함) |
| [07 M2 분석](docs/design/07-m2-analysis-notes.md) · [08 M4 업무](docs/design/08-m4-task-notes.md) · [09 M3 RAG](docs/design/09-m3-rag-notes.md) | 마일스톤별 구현 기록·설계 결정·검증 결과 |
| [평가](docs/evaluation.md) | 평가 데이터·지표·실험 결과 |
| [주요 오류와 개선 사례](docs/portfolio/troubleshooting.md) | 실제 발생한 문제와 해결 |
| [면접 Q&A](docs/portfolio/interview-qa.md) · [시연 시나리오](docs/portfolio/demo-scenario.md) · [이력서 요약](docs/portfolio/resume-summary.md) | 포트폴리오 |

## 프로젝트 구조

```
app/
  api/ services/ domain/ models/ schemas/   계층별 코드
  pipeline/    PDF 추출·정제·청킹
  extraction/  구조화 추출 스키마·프롬프트·인용 검증
  rag/         색인·검색·답변 생성
  llm/         OpenAI·Fake 구현, 구조화 출력 공통 흐름
  workers/     분석 실행기
migrations/    Alembic
tests/         unit / integration / live
evaluation/    평가 데이터셋·지표·실험 스크립트·결과
scripts/       로컬 DB, 고아 파일 정리
```

## 한계

- 인증·권한 미구현 (단일 사용자 데모). 감사 이벤트의 행위자는 `UNAUTHENTICATED_CLIENT`로만 기록
- 스캔(이미지) PDF는 OCR 미지원 → `NO_TEXT_LAYER`
- BackgroundTasks는 프로세스 재시작 시 실행 중 작업이 사라짐 (정리만 하고 자동 재실행 없음)
- 평가는 직접 작성한 가상 계약서 기준이며 실제 업무 문서 성능을 대표하지 않음
- 문서·질문 내용이 외부 LLM API(OpenAI)로 전송됨
