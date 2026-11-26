# 08. M4 검토 업무(Task) 관리 구현 기록

> 작성: 2026-11-06 · 브랜치 `feature/m4-task-management`

## 1. 구현 범위

| 기능 | API |
|---|---|
| 업무 생성 (직접 입력) | `POST /api/v1/documents/{id}/tasks` `{title, ...}` |
| AI 제안 승인 → 업무 생성 | `POST /api/v1/documents/{id}/tasks` `{source: {analysis_id, review_item_id}}` |
| 목록 (상태·우선순위·담당자 필터) | `GET /api/v1/documents/{id}/tasks` |
| 상세 | `GET /api/v1/tasks/{task_id}` |
| 상태·담당자·우선순위·기한 변경, 완료 처리 | `PATCH /api/v1/tasks/{task_id}` `{version, ...}` |
| 처리 이력 | `GET /api/v1/tasks/{task_id}/history` |

## 2. 설계 결정

| 결정 | 이유 |
|---|---|
| **AI는 제안만, 업무 생성은 사용자 요청으로만** | AI 결과가 사람 확인 없이 업무로 확정되거나 외부에 통보되지 않게 한다. 분석 후 업무 수가 0인 것을 테스트로 보장 |
| 제안 승인 시 비운 필드는 제안 내용(제목·사유·우선순위)으로 채우고, 사용자가 보낸 값이 우선 | "승인" 한 번으로 등록할 수 있으면서 사용자가 수정할 수 있게 |
| `(source_analysis_id, source_item_id)` **부분 유니크 인덱스** + 앱에서 409 변환 | 같은 제안 중복 승인 방지. 동시 요청 경쟁은 DB가 마지막에 막는다 |
| `source='AI_SUGGESTION'`이면 출처 분석·항목이 반드시 있어야 하는 CHECK 제약 | 출처를 추적할 수 없는 AI 업무가 생기지 않게 |
| **낙관적 잠금**(`version`): 읽은 version 비교 + `UPDATE … WHERE version = ?` | 두 사람이 동시에 고쳐도 나중 요청이 조용히 덮어쓰지 않는다. 행 잠금을 오래 잡지 않아 대기가 없다 |
| 바뀐 값이 없으면 version을 올리지 않음 | 같은 요청 재전송(재시도)이 충돌을 만들지 않게 (멱등) |
| `completed_at`은 `DONE`일 때만 존재 (CHECK + 서비스) | 완료 시각이 상태와 어긋나지 않게 |
| 별도 `task_histories` 대신 `audit_events`에 필드별 `{from, to}` 기록 | 문서 이력 API에서 업로드·분석·업무 이벤트를 한 번에 시간순으로 조회 |

**상태 전이**: `TODO → IN_PROGRESS | CANCELED`, `IN_PROGRESS → TODO | DONE | CANCELED`, `DONE → IN_PROGRESS`(재개), `CANCELED → TODO`(복구). 그 외는 `422 INVALID_STATE_TRANSITION`.

## 3. 검증 결과 (2026-11-06)

| 항목 | 결과 |
|---|---|
| 자동 테스트 (전체) | 193 passed (M4 추가분: 단위 상태 전이 16 + 스키마 8, 통합 20) |
| 실서버 확인 (uvicorn + PostgreSQL 18.6, 실제 분석 결과 사용) | 제안 승인 201 → 같은 제안 재승인 409 `TASK_ALREADY_EXISTS` → 오래된 version 수정 409 `VERSION_CONFLICT` → 완료 처리 시 `completed_at` 기록 → 이력 3건 |

## 4. 한계

- 인증이 없으므로 `assignee`는 검증되지 않은 자유 문자열이고, 이력의 행위자는 `UNAUTHENTICATED_CLIENT`로만 기록된다. "누가 바꿨는지"는 보장하지 않는다.
- 업무 생성·변경 알림(메일·메신저)은 범위 밖이다.
- 문서를 삭제하면 업무는 API에서 숨겨지지만 행은 남는다 (영구 삭제 정책은 후속).
