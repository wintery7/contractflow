"""근거 인용문을 원문과 대조한다.

LLM이 스스로 매기는 '신뢰도 점수'는 근거로 쓰지 않는다. 대신 결정적으로 검증할 수 있는 사실,
즉 "인용문이 정말 그 페이지에 있는가"를 확인해 VERIFIED / UNVERIFIED로 표시한다.
VERIFIED는 '인용문이 원문에 존재한다'는 뜻이지 '추출 값이 법적으로 옳다'는 뜻이 아니다.
원문에 있더라도 AI에게 내리는 지시처럼 보이는 인용문은 SUSPICIOUS로 표시한다 (injection.py).
"""

import unicodedata
from typing import Any

from app.extraction.injection import looks_like_instruction, pages_with_instructions
from app.extraction.schemas import (
    FIELD_NAMES,
    AnalysisResult,
    ContractExtraction,
    DocumentStats,
    Evidence,
    ExtractedField,
    FieldResult,
    ReviewItemResult,
    Verification,
    VerifiedEvidence,
)
from app.pipeline.pdf_extractor import PageText

# 둥근 따옴표·낫표를 곧은 따옴표로 통일 (PDF와 LLM 출력의 따옴표 모양 차이 흡수)
_QUOTE_EQUIVALENTS = str.maketrans(
    {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "「": '"', "」": '"'}
)
_MIN_QUOTE_CHARS = 2


def _squash(text: str) -> str:
    """대조용 정규화: NFC, 따옴표 통일, 모든 공백 제거 (PDF 줄바꿈 위치 차이를 흡수)."""
    text = unicodedata.normalize("NFC", text).translate(_QUOTE_EQUIVALENTS)
    return "".join(text.split())


class EvidenceVerifier:
    def __init__(self, pages: list[PageText]) -> None:
        self._pages = {page.page_no: _squash(page.text) for page in pages}

    def is_verified(self, evidence: Evidence) -> bool:
        quote = _squash(evidence.quote)
        if len(quote) < _MIN_QUOTE_CHARS or evidence.page not in self._pages:
            return False
        if quote in self._pages[evidence.page]:
            return True
        # 인용이 페이지 경계에 걸친 경우: 해당 페이지 + 다음 페이지를 이어서 확인
        joined = self._pages[evidence.page] + self._pages.get(evidence.page + 1, "")
        return quote in joined

    def verify_all(self, evidence: list[Evidence]) -> tuple[list[VerifiedEvidence], Verification]:
        verified = []
        for e in evidence:
            found = self.is_verified(e)
            verified.append(
                VerifiedEvidence(
                    page=e.page,
                    quote=e.quote,
                    verified=found,
                    suspicious=found and looks_like_instruction(e.quote),
                )
            )
        if not verified:
            return verified, "NOT_APPLICABLE"
        # 지시문 인용이 하나라도 있으면 가장 먼저 알린다. 문서 자체가 조작되었을 수 있다는 신호다.
        if any(v.suspicious for v in verified):
            return verified, "SUSPICIOUS"
        return verified, "VERIFIED" if all(v.verified for v in verified) else "UNVERIFIED"


def build_result(
    extraction: ContractExtraction, pages: list[PageText], stats: DocumentStats
) -> AnalysisResult:
    verifier = EvidenceVerifier(pages)
    warnings: list[str] = []
    fields: dict[str, Any] = {}

    for name in FIELD_NAMES:
        field: ExtractedField[Any] = getattr(extraction, name)
        evidence, verification = verifier.verify_all(field.evidence)
        fields[name] = FieldResult[Any](
            status=field.status, value=field.value, evidence=evidence, verification=verification
        )
        if verification == "UNVERIFIED":
            warnings.append(f"{name}: some evidence quotes were not found in the source text.")
        elif verification == "SUSPICIOUS":
            warnings.append(
                f"{name}: evidence looks like an instruction to an AI rather than contract text "
                "(possible prompt injection)."
            )

    review_items = []
    for index, item in enumerate(extraction.review_items, start=1):
        evidence, verification = verifier.verify_all(item.evidence)
        review_items.append(
            ReviewItemResult(
                item_id=f"r{index}",
                title=item.title,
                reason=item.reason,
                priority=item.priority,
                evidence=evidence,
                verification=verification,
            )
        )

    start, end = extraction.start_date.value, extraction.end_date.value
    if start and end and start > end:
        warnings.append("start_date is later than end_date.")
    if stats.empty_pages:
        warnings.append(
            f"Pages {stats.empty_pages} have no extractable text (possibly scanned images)."
        )
    # 모델이 지시를 따르면서 다른 문장을 인용한 경우도 있으므로 문서 전체도 따로 확인한다.
    if injected_pages := pages_with_instructions(pages):
        warnings.append(
            f"Pages {injected_pages} contain text that looks like instructions to an AI "
            "(possible prompt injection). Review every extracted value against the original."
        )

    return AnalysisResult(
        **fields, review_items=review_items, document_stats=stats, warnings=warnings
    )
