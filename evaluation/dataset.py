"""평가 데이터 로딩과 검증."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.pdf_extractor import PageText
from evaluation.datasets.contracts import CONTRACTS
from evaluation.metrics import squash

QUESTIONS_PATH = Path(__file__).parent / "datasets" / "questions.jsonl"
QUESTION_TYPES = {"fact", "location", "multi", "not_in_doc", "ambiguous", "similar_clause"}


@dataclass(frozen=True)
class Question:
    id: str
    contract: str
    type: str
    question: str
    # True: 문서로 답할 수 있음 / False: 문서에 없음 / None: 모호 (정확도 집계에서 제외)
    answerable: bool | None
    evidence: tuple[str, ...]
    keywords: tuple[str, ...]


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        questions.append(
            Question(
                id=raw["id"],
                contract=raw["contract"],
                type=raw["type"],
                question=raw["question"],
                answerable=raw["answerable"],
                evidence=tuple(raw["evidence"]),
                keywords=tuple(raw["keywords"]),
            )
        )
    return questions


def contract_pages(contract: str) -> list[PageText]:
    return [PageText(i, text) for i, text in enumerate(CONTRACTS[contract], start=1)]


def validate(questions: list[Question]) -> list[str]:
    """데이터셋 오류 목록. 비어 있으면 정상."""
    errors = []
    seen = set()
    for q in questions:
        if q.id in seen:
            errors.append(f"{q.id}: duplicate id")
        seen.add(q.id)
        if q.contract not in CONTRACTS:
            errors.append(f"{q.id}: unknown contract {q.contract}")
            continue
        if q.type not in QUESTION_TYPES:
            errors.append(f"{q.id}: unknown type {q.type}")
        if q.answerable is False and q.evidence:
            errors.append(f"{q.id}: not answerable but has evidence")
        if q.answerable is not False and not q.evidence:
            errors.append(f"{q.id}: answerable question needs evidence")
        full_text = squash("".join(CONTRACTS[q.contract]))
        for snippet in q.evidence:
            if squash(snippet) not in full_text:
                errors.append(f"{q.id}: evidence not found in contract: {snippet}")
    return errors
