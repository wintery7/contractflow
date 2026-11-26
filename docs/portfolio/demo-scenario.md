# 시연 시나리오 (약 7분)

Swagger UI(`http://localhost:8000/docs`)에서 진행한다. 시연용 PDF는 아래 명령으로 만든다.

```bash
uv run python -c "from tests.factories import make_korean_pdf; from tests.fixtures.sample_contract import SAMPLE_CONTRACT_PAGES; open('demo_contract.pdf','wb').write(make_korean_pdf(SAMPLE_CONTRACT_PAGES))"
```

| # | 단계 | 요청 | 보여 줄 것 |
|---|---|---|---|
| 1 | 업로드 | `POST /api/v1/documents` (demo_contract.pdf) | 201, `Location` 헤더, 상태 `UPLOADED` |
| 2 | 잘못된 파일 | PNG 파일 이름만 `.pdf`로 바꿔 업로드 | 415 `UNSUPPORTED_MEDIA_TYPE` — 확장자가 아니라 내용(매직 바이트)을 검사 |
| 3 | 중복 업로드 | 1과 같은 파일 다시 업로드 | 409 `DOCUMENT_ALREADY_EXISTS` + 기존 문서 ID |
| 4 | 분석 시작 | `POST /documents/{id}/analyses` | **즉시 202** + 분석 ID (비동기) |
| 5 | 진행 확인 | `GET /analyses/{analysis_id}` 반복 | `stage`가 EXTRACTING → … → FIELD_EXTRACTION → `SUCCEEDED` |
| 6 | 분석 결과 | 같은 응답의 `result` | 필드별 값·`evidence`(원문 인용·페이지)·`verification: VERIFIED`, 문서에 없는 값은 `NOT_FOUND`, `disclaimer` |
| 7 | 재요청 | 4를 다시 실행 | 200, 같은 분석 ID — LLM을 다시 부르지 않음 |
| 8 | 질의응답 | `POST /documents/{id}/questions` `{"question": "중도 해지 조건은?"}` | `ANSWERED`, 답변, 인용된 청크(`cited_by_answer: true`)의 페이지·점수 |
| 9 | 문서에 없는 질문 | `{"question": "준거법과 관할 법원은?"}` | `INSUFFICIENT_EVIDENCE` — 지어내지 않음 |
| 10 | AI 제안 승인 | `POST /documents/{id}/tasks` `{"source": {"analysis_id": "...", "review_item_id": "r1"}}` | 201, 제목·우선순위가 제안 내용으로 채워짐, `source: AI_SUGGESTION` |
| 11 | 같은 제안 재승인 | 10 반복 | 409 `TASK_ALREADY_EXISTS` |
| 12 | 상태 변경 | `PATCH /tasks/{id}` `{"version": 1, "status": "IN_PROGRESS", "assignee": "kim"}` | 200, `version: 2` |
| 13 | 동시 수정 충돌 | 같은 요청을 `version: 1`로 다시 | 409 `VERSION_CONFLICT` + 현재 version |
| 14 | 이력 | `GET /documents/{id}/history` | 업로드 → 분석 요청·시작·성공 → 업무 생성·변경이 시간순, 변경 필드 from/to |
| 15 | 삭제 | `DELETE /documents/{id}` → `GET /documents/{id}` | 204 → 404, 원문 페이지·청크·파일 삭제 |

## 말로 설명할 포인트

- 4~5: "LLM 호출이 10초 이상 걸릴 수 있어 비동기로 처리했고, 상태의 정본은 DB입니다. 서버가 재시작되면 중단된 분석은 INTERRUPTED로 정리됩니다."
- 6: "VERIFIED는 서버가 인용문을 원문과 대조했다는 뜻입니다. 모델의 자기 신뢰도 점수는 쓰지 않았습니다."
- 8~9: "유사도가 낮으면 LLM을 부르지 않고, 모델이 실제 발췌문을 인용하지 않으면 답을 돌려주지 않습니다."
- 10~11: "AI는 제안만 하고, 업무 등록은 사용자 승인으로만 됩니다. 같은 제안 중복은 DB 제약으로 막습니다."
- 마무리: "분석 결과는 법률 자문이 아닌 검토 보조 자료이고, 인증이 없는 데모라는 한계가 있습니다."
