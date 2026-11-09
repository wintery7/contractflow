# 09. M3 RAG 구현 기록

> 작성: 2026-11-09 · 브랜치 `feature/m3-rag`

## 1. 파이프라인

```mermaid
flowchart LR
    subgraph 색인["색인 (분석 실행 중)"]
        A[PDF] --> B[페이지별 추출·정제] --> C[조항 경계 청킹<br/>page_start~page_end 보존]
        C --> D[임베딩<br/>text-embedding-3-small] --> E[(document_chunks<br/>vector 1536)]
    end
    subgraph 질의["질의응답 (요청마다)"]
        Q[질문] --> QE[질문 임베딩] --> S[문서 범위 정확 코사인 검색<br/>top-k]
        E --> S
        S --> T{최고 유사도 ≥ 임계값?}
        T -- 아니오 --> N1[INSUFFICIENT_EVIDENCE<br/>LOW_RETRIEVAL_SCORE<br/>LLM 미호출]
        T -- 예 --> G[LLM 답변 생성<br/>C1..Ck 라벨 인용]
        G --> V{유효한 인용?}
        V -- 거절 --> N2[MODEL_DECLINED]
        V -- 없음 --> N3[NO_VALID_CITATION<br/>답 미반환]
        V -- 있음 --> OK[ANSWERED + 근거 청크·페이지·점수]
    end
```

| 단계 | 모듈 | 입력 → 출력 |
|---|---|---|
| 청킹 | `app/pipeline/chunker.py` | `list[PageText]` → `list[Chunk(index, page_start, page_end, content)]` |
| 임베딩 | `app/llm/embeddings.py` | `list[str]` → 벡터 목록 (OpenAI / Fake) |
| 색인 | `app/rag/indexer.py` | 청크 + 벡터 → `document_chunks` 교체 (한 트랜잭션) |
| 검색 | `app/rag/retriever.py` | 질문 벡터 → `RetrievedChunk(score)` 상위 k개 |
| 답변 | `app/rag/answerer.py` | 질문 + 청크 → `AnswerOutput(answerable, answer, cited_chunks)` |
| 판정 | `app/services/qa_service.py::resolve_answer` | 모델 출력 → 최종 상태 (서비스·평가 공용) |

## 2. 설계 결정

| 결정 | 이유 |
|---|---|
| **pgvector + 문서 범위 정확 검색 (ANN 인덱스 없음)** | 질문은 항상 한 문서(수십~수백 청크) 범위. `(document_id, chunk_index)` 유니크 인덱스로 범위를 좁힌 뒤 정확한 거리 계산이 빠르고 정확하다. HNSW에 문서 필터를 걸면 탐색 후 필터링 때문에 k개보다 적게 나올 수 있다. 문서 간 검색이 생기면 HNSW 추가 |
| 별도 VectorDB 대신 pgvector | 문서 삭제 시 청크·벡터를 **같은 트랜잭션**에서 지울 수 있다 (분산 삭제·고아 벡터 없음) |
| 조항 경계 우선 청킹 | 계약 질문은 대부분 특정 조항에 관한 것. "제N조"에서 새 청크를 시작해 조항이 쪼개지지 않게 한다 |
| 청크마다 페이지 범위 보존 | 답변 근거에 원문 페이지를 표시하기 위해 |
| `embedding_model` 컬럼 + 불일치 시 409 | 모델이 바뀌면 벡터 공간이 달라 거리 비교가 무의미하다 |
| **2단계 근거 판단** | ① 검색 점수가 임계값 미만이면 LLM을 부르지 않는다 (비용·환각 방지) ② 모델이 거절하거나 실제로 넘긴 청크를 인용하지 않으면 답을 돌려주지 않는다 |
| 유사도 점수 ≠ 정확성 | 점수는 "주제가 비슷하다"는 신호다. 응답 스키마 설명에 명시하고, 답변의 근거 일치는 평가셋으로 따로 측정 |
| 청크 라벨(`C1`)로 인용 | UUID를 모델에 노출하지 않고, 서버가 라벨 → 청크 매핑으로 검증 |
| 질문·발췌문 구획 태그 무력화 | `</question>` 같은 문자열로 구획을 탈출하는 인젝션 방지 (단위 테스트) |
| 구조화 출력 흐름 공통화 | 추출과 질의응답이 같은 "호출 → 검증 → 1회 교정" 흐름을 쓴다 (`llm/structured.py`) |
| 분석 파이프라인 버전 `m3-v1` | 색인이 없는 이전 분석 결과를 재사용하지 않도록 |

## 3. 검증 결과

| 항목 | 결과 (2026-11-09) |
|---|---|
| 자동 테스트 (Fake LLM·Fake 임베딩, 실제 PostgreSQL + pgvector 0.6.2) | 전체 227 passed (M3 추가: 청킹·임베딩·답변 입력 단위 15, 색인 통합 4, 질의응답 통합 15) |
| 실제 OpenAI live 테스트 (`tests/live/test_openai_rag.py`) | **미실행** — 작업 중 API 키가 401로 거부됨. 키 교체 후 실행 예정 |
| 검색 품질 평가 | [docs/evaluation.md](../evaluation.md) 참고 |

## 4. 한계

- 재정렬(reranking)은 넣지 않았다. 평가 결과에서 순위 문제가 확인될 때만 추가한다.
- 질문 하나에 문서 하나만 대상으로 한다. 여러 계약서를 가로지르는 검색은 범위 밖이다.
- 대화 맥락(이전 질문)을 기억하지 않는다.
- 질문·답변 본문은 저장하지 않는다 (호출 메타데이터만 기록). 질의 이력 기능이 필요하면 보존 정책과 함께 추가해야 한다.
