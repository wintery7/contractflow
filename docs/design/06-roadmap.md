# 06. 6주 구현 순서 · 마일스톤 완료 조건

> 상태: M0 초안 (2026-10-16) · 하루 약 2시간 기준(주 10~12시간). 매주 말 실제 진행률로 재조정한다.

## 1. 주차별 계획

| 주차 | 마일스톤 | 작업 | 주말 검증 기준 |
|---|---|---|---|
| 1 | M0 → M1 | 설계 검토·확정, Docker·git·uv 세팅, FastAPI 골격, 설정/로그/오류 형식, documents 모델·마이그레이션, 업로드/목록/상세/삭제, 통합 테스트 | 아래 "M1 완료 조건" |
| 2 | M2 + M4 | PDF 추출·정제·빈 문서 감지, analyses 테이블·상태 머신, BackgroundTasks 실행기, `LLMClient`+Fake, 구조화 추출 + 인용 검증 + 교정 재시도 / tasks·audit_events, Task 상태 전이·낙관적 잠금, 이력 API | Fake LLM으로 업로드→분석→결과→Task 생성→상태 변경→이력 조회 E2E 테스트 통과. 실제 LLM으로 샘플 계약서 1건 수동 검증 |
| 3 | M3 | 임베딩 모델 결정, 청커(페이지 보존·조항 경계), chunks 마이그레이션(vector), 색인, 검색, 답변 생성, 인용 검증, 근거 부족 처리 | RAG 테스트(출처·페이지 유지, 근거 없음, LLM 실패, 잘못된 인용) 통과. 예시 질문 5개 수동 검증 기록 |
| 4 | M5(품질) | 평가 계약서 3~5건 작성(표준계약서 기반 가상 데이터), 평가셋 30+ 문항, Recall@k·MRR 하네스, 실험 순서: 청크 크기 → 오버랩 → top-k → (BM25 비교) / 근거 부족 임계값 결정, 오류 처리 보강 | `eval/results/`에 실제 실행 결과와 실행 조건 기록 |
| 5 | M5(운영) | 앱 Dockerfile, compose 전체 실행, JSON 로그·request_id, 지연 측정(p50/p95), 고아 파일 정리, 테스트 확대·커버리지 확인, README·아키텍처·ERD·API 문서 정리 | 깨끗한 환경에서 `docker compose up` 한 번으로 실행 + 테스트 전체 통과 |
| 6 | M6 | 시연 시나리오·영상, 기술 면접 Q&A, 이력서 요약(검증된 사실만), 주요 오류/개선 사례 정리, 회고 | 다른 사람이 README만 보고 실행·시연 가능 |

### 일정이 밀릴 때 자르는 순서
1. 하이브리드 검색·Reranking → 2. 워커 프로세스 분리 → 3. Task 이력 API 세부 필터 → 4. 평가 문항 수(최소 30 유지) 대신 실험 수 축소
**자르지 않는 것**: 근거 인용·검증, 근거 부족 시 답변 거부, 상태 전이 규칙, 통합 테스트, 평가 하네스, Docker 실행.

## 2. M1 완료 조건 (첫 구현 단계)

브랜치 `feature/m1-backend-foundation` → `develop` 머지 시점에 모두 충족해야 한다.

### 환경
- [ ] `docker compose up -d db` 후 `pg_isready` 성공, `CREATE EXTENSION vector` 가능 확인
- [ ] `uv sync` 만으로 의존성 설치 재현 (`uv.lock` 커밋)
- [ ] 환경변수 목록·기본값이 README에 문서화, `.env`·`.env.*`·업로드 폴더는 `.gitignore`

### 기능
- [ ] `uv run alembic upgrade head` 로 `documents`, `audit_events` 생성, `alembic downgrade base` 후 재적용 성공
- [ ] `POST /api/v1/documents`: PDF 업로드 201, 파일이 `STORAGE_DIR/{uuid}.pdf`로 저장
- [ ] 비PDF 415, 빈 파일 400, 크기 초과 413, 중복 409 — 공통 오류 형식으로 반환
- [ ] `GET /documents`(status 필터·페이지네이션), `GET /documents/{id}`, `DELETE /documents/{id}`(소프트 삭제 + 파일 삭제)
- [ ] 업로드·삭제 시 `audit_events` 기록, `GET /documents/{id}/history` 조회
- [ ] `domain/document_status.py` 상태 전이 함수 (M2에서 사용, M1에서 단위 테스트)
- [ ] `/health/live`, `/health/ready`
- [ ] 모든 응답에 `X-Request-ID`, 요청 로그가 JSON 한 줄로 출력되고 파일 내용은 로그에 없음

### 품질
- [ ] `uv run pytest` 전체 통과 (단위: 상태 전이 전체 조합, 파일명 정규화, 오류 변환 / 통합: 위 API 시나리오 전부)
- [ ] `uv run ruff check .` · `ruff format --check .` 통과
- [ ] Swagger UI(`/docs`)에서 업로드→조회→삭제 수동 확인
- [ ] 커밋이 기능 단위로 나뉘어 있고 메시지가 `feat:/test:/chore:` 규칙을 따름

### 이해도 확인 (면접 대비)
- [ ] "왜 상태를 DB에 두고 BackgroundTasks로 실행하는가, 무엇이 위험한가"를 1분 안에 설명
- [ ] "중복 업로드/중복 분석을 애플리케이션 if문이 아니라 DB 제약으로 막는 이유" 설명
- [ ] "업로드 파일을 원본 파일명으로 저장하면 안 되는 이유" 설명
