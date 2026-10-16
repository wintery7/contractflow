# 04. API 명세 초안

> 상태: M0 초안 (2026-10-16) · 구현 후에는 FastAPI가 생성하는 OpenAPI(`/docs`)가 정본이며 이 문서는 설계 의도와 테스트 시나리오를 기록한다.

## 공통 규약

- Base URL: `/api/v1`, JSON(`application/json`), 시간은 ISO 8601 UTC, ID는 UUID
- **인증: MVP 미구현** (모든 엔드포인트 공통). 로컬 단일 사용자 데모 전용.
- 목록: `?limit=20&offset=0` (limit 최대 100), 응답 `{items, total, limit, offset}`
- 모든 응답 헤더에 `X-Request-ID`
- 오류 응답 형식 (모든 오류 공통):

```json
{
  "error": {
    "code": "INVALID_STATE_TRANSITION",
    "message": "Task cannot move from DONE to CANCELED.",
    "details": {"from": "DONE", "to": "CANCELED"},
    "request_id": "9f1c…"
  }
}
```

| HTTP | 대표 code |
|---|---|
| 400 | `EMPTY_FILE`, `INVALID_REQUEST` |
| 404 | `DOCUMENT_NOT_FOUND`, `TASK_NOT_FOUND`, `ANALYSIS_NOT_FOUND` |
| 409 | `DOCUMENT_ALREADY_EXISTS`, `ANALYSIS_IN_PROGRESS`, `DOCUMENT_NOT_READY`, `VERSION_CONFLICT`, `DOCUMENT_BUSY` |
| 413 | `FILE_TOO_LARGE` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 422 | `VALIDATION_ERROR`(FastAPI 기본 형식을 공통 형식으로 변환), `INVALID_STATE_TRANSITION` |
| 503 | `LLM_UNAVAILABLE`, `EMBEDDING_UNAVAILABLE` (+ `Retry-After`) |

## 요구 경로와의 차이

| 요구안 | 설계안 | 이유 |
|---|---|---|
| `POST/GET /documents/{id}/analysis` | `POST/GET /documents/{id}/analyses`, `GET /documents/{id}/analyses/latest`, `GET /analyses/{analysis_id}` | 분석이 1:N이므로 컬렉션 리소스. 상태 폴링은 분석 ID로 직접 조회 |
| (없음) | `GET /tasks/{id}/history` | Task 처리 이력 조회 요구사항 |
| (없음) | `GET /health/live`, `/health/ready` | 운영·Docker 헬스체크 |

---

## 1. 문서

### 1.1 `POST /documents` — 업로드
| 항목 | 내용 |
|---|---|
| 요청 | `multipart/form-data`, `file` (필수) |
| 응답 `201` | `DocumentResponse` + `Location` 헤더 |
| 오류 | 400 빈 파일 · 413 크기 초과 · 415 PDF 아님 · 409 동일 파일 존재(`details.existing_document_id`) |
| 검증 | 매직바이트 `%PDF-`, 크기 ≤ `MAX_UPLOAD_BYTES`(스트리밍 중 초과 시 즉시 중단), 파일명 정규화 |
| DB 변경 | `documents` INSERT, `audit_events` INSERT |
| 비동기 | 없음 (분석은 별도 요청) |

```json
// DocumentResponse
{
  "id": "uuid", "original_filename": "service_agreement.pdf",
  "size_bytes": 482113, "status": "UPLOADED", "page_count": null,
  "error_code": null, "created_at": "...", "updated_at": "...",
  "latest_analysis_id": null
}
```
테스트: 정상 업로드 201 / 확장자는 .pdf지만 내용이 PNG → 415 / 0바이트 → 400 / 한도+1바이트 → 413 / 같은 파일 2회 → 409 / 파일명 `../../etc/passwd.pdf` → 저장 키는 UUID, 파일명은 정규화.

### 1.2 `GET /documents` — 목록
- Query: `status`, `limit`, `offset` · `200 Page[DocumentResponse]` · 422 잘못된 status · DB 변경 없음
- 테스트: 삭제된 문서 제외 / status 필터 / 최신순 정렬 / limit 101 → 422

### 1.3 `GET /documents/{document_id}` — 상세
- `200 DocumentResponse` · 404 (없음 또는 삭제됨) · 테스트: 존재·부재·삭제 후 404, UUID 형식 오류 422

### 1.4 `DELETE /documents/{document_id}` — 삭제
| 항목 | 내용 |
|---|---|
| 응답 | `204` |
| 오류 | 404 · 409 `DOCUMENT_BUSY`(분석 진행 중) |
| DB 변경 | `deleted_at` 설정, pages·chunks 삭제, audit INSERT (한 트랜잭션) → 커밋 후 파일 삭제 |
| 테스트 | 삭제 후 상세 404, 청크 0건, 파일 부재 / 진행 중 409 / 두 번째 삭제 404 / 삭제 후 같은 파일 재업로드 201 |

## 2. 분석

### 2.1 `POST /documents/{document_id}/analyses` — 분석 시작
| 항목 | 내용 |
|---|---|
| 요청 | `{"force": false}` (선택) |
| 응답 `202` | `AnalysisResponse(status=QUEUED)` + `Location: /api/v1/analyses/{id}` |
| 응답 `200` | 같은 `pipeline_version`으로 성공한 분석이 이미 있고 `force=false` → 기존 결과 반환 (불필요한 LLM 비용 방지) |
| 오류 | 404 · 409 `ANALYSIS_IN_PROGRESS`(`details.analysis_id`) |
| 중복 방지 | 부분 유니크 인덱스 위반(동시 요청 경쟁)도 409로 변환 |
| DB 변경 | `document_analyses` INSERT, `documents.status=PROCESSING`, audit |
| 비동기 | ✅ BackgroundTasks |
| 테스트 | 202 후 폴링 시 SUCCEEDED(Fake LLM) / 진행 중 재요청 409 / 완료 후 재요청 200 동일 ID / force=true 202 새 ID / 스캔 PDF → FAILED `NO_TEXT_LAYER` / LLM 실패 → FAILED, document FAILED |

### 2.2 `GET /analyses/{analysis_id}` — 상태·결과 조회
```json
{
  "id": "uuid", "document_id": "uuid",
  "status": "SUCCEEDED", "stage": null,
  "llm_model": "…", "prompt_version": "extract-v1",
  "started_at": "...", "finished_at": "...",
  "error": null,
  "result": {
    "contract_title":   {"value": "소프트웨어 유지보수 계약서", "status": "FOUND",
                          "evidence": [{"page": 1, "quote": "소프트웨어 유지보수 계약서"}],
                          "verification": "VERIFIED"},
    "parties":          {"value": [{"name": "㈜가나", "role": "갑"}, {"name": "㈜다라", "role": "을"}], "...": "..."},
    "start_date":       {"value": "2026-01-01", "...": "..."},
    "end_date":         {"value": "2026-12-31", "...": "..."},
    "contract_amount":  {"value": {"amount": "12000000", "currency": "KRW"}, "...": "..."},
    "auto_renewal":     {"value": "만료 30일 전 서면 통지 없으면 1년 자동 연장", "...": "..."},
    "termination":      {"value": "...", "...": "..."},
    "penalty":          {"value": null, "status": "NOT_FOUND", "evidence": [], "verification": "UNVERIFIED"},
    "payment_terms":    {"value": "...", "...": "..."},
    "confidentiality":  {"value": "...", "...": "..."},
    "review_items": [
      {"item_id": "r1", "title": "자동 갱신 통지 기한 확인", "reason": "...", "priority": "HIGH",
       "evidence": [{"page": 3, "quote": "..."}], "verification": "VERIFIED"}
    ]
  },
  "disclaimer": "본 결과는 법률 자문이 아닌 검토 보조 자료입니다."
}
```
- 금액은 부동소수점 오차 방지를 위해 문자열 decimal.
- 404 · 테스트: QUEUED/RUNNING일 때 result null, FAILED일 때 error 코드 노출(내부 스택트레이스 미노출)

### 2.3 `GET /documents/{document_id}/analyses` · `GET /documents/{document_id}/analyses/latest`
- 목록은 요약(결과 제외), latest는 2.2와 동일. 분석 없음 → latest 404 `ANALYSIS_NOT_FOUND`

## 3. 질의응답

### 3.1 `POST /documents/{document_id}/questions`
| 항목 | 내용 |
|---|---|
| 요청 | `{"question": "중도 해지 조건은?", "top_k": 5}` — question 1~500자, top_k 1~20 |
| 응답 `200` | 아래 |
| 오류 | 404 · 409 `DOCUMENT_NOT_READY`(색인 없음) · 503 `LLM_UNAVAILABLE` |
| DB 변경 | `llm_calls` INSERT만 (질문·답변 본문은 저장하지 않음) |
| 비동기 | 없음 (동기, 타임아웃 적용) |

```json
{
  "question": "중도 해지 조건은?",
  "status": "ANSWERED",            // ANSWERED | INSUFFICIENT_EVIDENCE
  "answer": "어느 일방이 … 30일 전 서면 통지로 해지할 수 있습니다. [c-12]",
  "citations": [
    {"chunk_id": "uuid", "chunk_index": 12, "page_start": 4, "page_end": 4,
     "excerpt": "제12조(계약의 해지) ① …", "score": 0.83, "cited_by_answer": true}
  ],
  "retrieval": {"top_k": 5, "max_score": 0.83, "threshold": 0.45},
  "disclaimer": "본 결과는 법률 자문이 아닌 검토 보조 자료입니다."
}
```
- `score`는 코사인 유사도(1 - distance)이며 **답변 정확성을 의미하지 않음**을 스키마 설명에 명시.
- 테스트: 근거 있는 질문 → ANSWERED + 페이지 정확 / 문서에 없는 정보 → INSUFFICIENT_EVIDENCE, LLM 미호출 / LLM 타임아웃 → 503 / LLM이 존재하지 않는 청크 인용 → 해당 인용 제거·UNVERIFIED 처리 / 문서 안 "이전 지시를 무시하라" 문구 → 시스템 동작 불변

## 4. 업무(Task)

### 4.1 `POST /documents/{document_id}/tasks`
```json
{
  "title": "자동 갱신 통지 기한 확인", "description": "…",
  "priority": "HIGH", "assignee": "kim", "due_date": "2026-11-30",
  "source": {"analysis_id": "uuid", "review_item_id": "r1"}   // 선택. 있으면 source=AI_SUGGESTION
}
```
- `201 TaskResponse` · 404 문서/분석 없음 · 409 같은 제안이 이미 등록됨 · 422 title 1~200자, priority 값, due_date 형식, review_item_id가 해당 분석 결과에 없음
- DB: tasks INSERT(status=TODO, version=1), audit `TASK_CREATED`
- **AI 제안은 이 요청(사용자 행위)을 통해서만 Task가 된다.**

```json
// TaskResponse
{"id": "uuid", "document_id": "uuid", "title": "...", "description": "...",
 "priority": "HIGH", "status": "TODO", "assignee": "kim", "due_date": "2026-11-30",
 "source": "AI_SUGGESTION", "source_analysis_id": "uuid", "source_item_id": "r1",
 "version": 1, "created_at": "...", "updated_at": "...", "completed_at": null}
```

### 4.2 `GET /documents/{document_id}/tasks`
- Query: `status`, `priority`, `assignee`, `limit`, `offset` → `200 Page[TaskResponse]`

### 4.3 `GET /tasks/{task_id}` → `200 TaskResponse` · 404

### 4.4 `PATCH /tasks/{task_id}` — 상태·담당자·우선순위·기한 변경, 완료 처리
```json
{"version": 3, "status": "DONE", "assignee": "lee", "priority": "MEDIUM", "due_date": null}
```
- `version` 필수, 나머지는 보낸 필드만 변경(`exclude_unset`). 완료 처리 = `status: DONE`(`completed_at` 자동 설정)
- `200 TaskResponse(version+1)` · 404 · 409 `VERSION_CONFLICT` · 422 `INVALID_STATE_TRANSITION`/빈 변경
- DB: tasks UPDATE, audit `TASK_UPDATED`(변경 필드 before/after)
- 테스트: 허용 전이 표 전체(파라미터화) / 오래된 version 409 / DONE→CANCELED 422 / 변경 없는 PATCH 422

### 4.5 `GET /tasks/{task_id}/history` → `200 Page[AuditEventResponse]`

## 5. 이력

### 5.1 `GET /documents/{document_id}/history`
- Query: `limit`, `offset` · 시간 오름차순
```json
{"items": [
  {"id": 1, "occurred_at": "...", "actor_type": "UNAUTHENTICATED_CLIENT",
   "action": "DOCUMENT_UPLOADED", "entity_type": "DOCUMENT", "entity_id": "uuid",
   "outcome": "SUCCESS", "changes": null}
], "total": 1, "limit": 20, "offset": 0}
```
- 삭제된 문서도 이력은 조회 가능하게 할지 → 기본안: **404** (삭제 문서는 모든 API에서 비노출, DB에는 남음)

## 6. 헬스체크
- `GET /health/live` → `200 {"status":"ok"}` · `GET /health/ready` → DB `SELECT 1` 성공 시 200, 실패 시 503
