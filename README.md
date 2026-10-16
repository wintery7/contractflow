# ContractFlow AI

계약서 PDF를 업로드하면 LLM과 RAG로 핵심 정보를 근거와 함께 추출하고, 검토 업무와 처리 이력을 관리하는 백엔드 API.

> ⚠️ 분석 결과는 법률 자문이 아닌 **검토 보조 자료**입니다.
> ⚠️ 인증·권한이 **구현되어 있지 않습니다.** 로컬 단일 사용자 데모 전용입니다.

## 현재 진행 상태

| 마일스톤 | 상태 |
|---|---|
| M0 요구사항·설계 | 완료 — [docs/design](docs/design/) |
| M1 백엔드 기반 (문서 업로드/조회/삭제, 이력, 마이그레이션, 테스트) | 구현 완료, Docker 환경 검증 대기 |
| M2 문서 분석 | 예정 |

## 빠른 시작

요구사항: Python 3.11.9, [uv](https://docs.astral.sh/uv/), Docker Desktop

```bash
cp .env.example .env                 # 값 채우기 (기존 .env가 있으면 필요한 키만 추가)
docker compose up -d db              # PostgreSQL 16 + pgvector
uv sync                              # 의존성 설치 (uv.lock 기준)
uv run alembic upgrade head          # 스키마 생성
uv run uvicorn app.main:app --reload --no-access-log
```

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
