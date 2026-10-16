# 05. 폴더 구조 · 개발 환경

> 상태: M0 초안 (2026-10-16)

## 1. 권장 폴더 구조

```
contract-flow/
├── app/
│   ├── main.py                  # 앱 팩토리, 라우터·미들웨어·예외 핸들러 등록
│   ├── core/
│   │   ├── config.py            # pydantic-settings (환경변수 → Settings)
│   │   ├── logging.py           # JSON 로그 포매터, 민감정보 마스킹
│   │   ├── errors.py            # 도메인 예외(AppError 계층) → HTTP 오류 매핑
│   │   └── middleware.py        # X-Request-ID
│   ├── db/
│   │   ├── base.py              # DeclarativeBase, 공통 컬럼(mixin)
│   │   └── session.py           # engine, SessionLocal, get_db 의존성
│   ├── models/                  # SQLAlchemy ORM (테이블당 1파일)
│   ├── schemas/                 # Pydantic 요청/응답 모델 (ORM과 분리)
│   ├── domain/                  # 순수 규칙: 상태 머신, 값 객체 (I/O 없음)
│   │   ├── document_status.py
│   │   └── task_status.py
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/  documents.py  analyses.py  questions.py  tasks.py  health.py
│   ├── services/                # 유스케이스 + 트랜잭션 경계 + 감사 이벤트
│   │   ├── document_service.py  analysis_service.py  qa_service.py
│   │   ├── task_service.py      audit_service.py
│   ├── storage/file_storage.py  # FileStorage 프로토콜, LocalFileStorage
│   ├── pipeline/                # 문서 처리 단계 (각각 입력→출력 함수)
│   │   ├── pdf_extractor.py  text_cleaner.py  chunker.py  indexer.py
│   ├── extraction/              # 구조화 추출: 스키마, 프롬프트, 인용 검증
│   ├── rag/                     # retriever.py  prompt_builder.py  answerer.py
│   ├── llm/                     # base.py(LLMClient, Embedder 프로토콜), <provider>.py, fake.py
│   └── workers/analysis_runner.py  # 분석 실행 오케스트레이션 (BackgroundTasks 진입점)
├── migrations/                  # Alembic
├── tests/
│   ├── conftest.py              # 테스트 DB, 트랜잭션 롤백 픽스처, Fake LLM 주입
│   ├── unit/                    # domain, chunker, cleaner, schemas, 오류 변환
│   ├── integration/             # API + 실제 PostgreSQL
│   ├── rag/                     # 검색·인용·근거 부족·LLM 실패 (Fake LLM)
│   ├── live/                    # 실제 외부 API 호출 (기본 skip, -m live로만 실행)
│   └── fixtures/                # 테스트용 PDF (텍스트 PDF, 빈 PDF, 이미지 PDF, 손상 PDF)
├── eval/
│   ├── datasets/                # 평가 계약서 PDF, qa_eval.jsonl (질문·정답 근거)
│   ├── run_retrieval_eval.py    # Recall@k, MRR
│   └── results/                 # 실험별 결과 (실행한 것만 커밋)
├── scripts/                     # 고아 파일 정리, 샘플 데이터 적재 등
├── docs/
│   ├── design/                  # 이 문서들
│   └── adr/                     # 주요 결정 기록 (필요할 때 추가)
├── docker-compose.yml           # db(pgvector), app
├── Dockerfile
├── pyproject.toml / uv.lock
├── alembic.ini
├── .env.example                 # 커밋 O
├── .env                         # 커밋 X
└── README.md
```

설계 원칙
- `domain/`은 FastAPI·SQLAlchemy를 import하지 않는다 → 가장 빠른 단위 테스트 대상.
- `schemas/`(API 계약)와 `models/`(저장 구조)를 분리해 DB 컬럼 변경이 API를 깨지 않게 한다.
- 외부 의존(LLM, 임베딩, 파일)은 프로토콜 + 의존성 주입 → 테스트에서 Fake로 교체.

## 2. 개발 환경

### 현재 확인된 상태 (2026-10-16 실행 결과)
| 도구 | 상태 |
|---|---|
| Python | 3.11.9 ✅ |
| uv | 0.12.5 ✅ |
| git | 2.55.0 ✅ (작업 폴더는 아직 git 저장소 아님) |
| Docker | ❌ 미설치 (WSL 미설치). **M1~M4는 로컬 DB(`scripts/local_db.py`, pgserver)로 개발, Docker 배포·검증은 M5** |

### 준비 절차
1. **Docker Desktop 설치** (WSL2 백엔드). 설치 후 `docker version`, `docker compose version` 확인.
2. git 초기화와 브랜치:
   ```bash
   git init -b main
   git commit --allow-empty -m "chore: initialize repository"
   git switch -c develop
   git switch -c feature/m1-backend-foundation
   ```
3. 의존성 (M1 범위만. AI 라이브러리는 M2/M3에서 추가):
   ```bash
   uv init --python 3.11
   uv add fastapi "uvicorn[standard]" "sqlalchemy>=2" "psycopg[binary]" alembic pydantic-settings python-multipart
   uv add --dev pytest httpx ruff
   ```
4. DB 실행 (M1에서는 db 서비스만 컨테이너, 앱은 로컬 실행 → 디버깅이 쉬움):
   ```yaml
   # docker-compose.yml (초안)
   services:
     db:
       image: pgvector/pgvector:pg16
       environment:
         POSTGRES_USER: contractflow
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
         POSTGRES_DB: contractflow
       ports: ["5432:5432"]
       volumes: [pgdata:/var/lib/postgresql/data]
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U contractflow"]
         interval: 5s
   volumes:
     pgdata:
   ```
   테스트 DB는 같은 컨테이너에 `contractflow_test` 데이터베이스를 별도로 만든다.
5. `.env.example`
   ```
   APP_ENV=local
   DATABASE_URL=postgresql+psycopg://contractflow:change-me@localhost:5432/contractflow
   TEST_DATABASE_URL=postgresql+psycopg://contractflow:change-me@localhost:5432/contractflow_test
   STORAGE_DIR=./var/uploads
   MAX_UPLOAD_BYTES=20971520
   LOG_LEVEL=INFO
   # M2 이후
   LLM_PROVIDER=fake
   LLM_API_KEY=
   EMBEDDING_PROVIDER=fake
   ```
6. 실행: `uv run alembic upgrade head` → `uv run uvicorn app.main:app --reload` → http://localhost:8000/docs

### 테스트 전략 요약
- 통합 테스트는 **실제 PostgreSQL** 사용 (SQLite는 pgvector, 부분 인덱스, JSONB 동작이 달라 의미 없음)
- 테스트마다 트랜잭션을 열고 끝나면 롤백 → 테스트 간 격리
- 외부 LLM: 기본은 `FakeLLMClient`(결정적 응답, 실패·잘못된 JSON 시나리오 주입). 실제 호출 테스트는 `@pytest.mark.live`로 분리하고 CI에서는 실행하지 않음
