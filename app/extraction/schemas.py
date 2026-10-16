"""구조화 추출 스키마.

두 종류의 모델을 구분한다.
- LLM 출력 모델(ContractExtraction): 모델이 채우는 형식. 응답마다 Pydantic으로 다시 검증한다.
- 결과 모델(AnalysisResult): 서버가 근거 인용을 원문과 대조한 뒤 저장·반환하는 형식.
"""

from datetime import date
from typing import Generic, Literal, Self, TypeVar

from pydantic import BaseModel, Field, model_validator

FieldStatus = Literal["FOUND", "NOT_FOUND", "AMBIGUOUS"]
Priority = Literal["LOW", "MEDIUM", "HIGH"]
Verification = Literal["VERIFIED", "UNVERIFIED", "NOT_APPLICABLE"]

V = TypeVar("V")


# ---------- LLM 출력 ----------


class Evidence(BaseModel):
    page: int = Field(ge=1, description="근거가 있는 [페이지 N]의 N")
    quote: str = Field(min_length=1, max_length=500, description="원문을 그대로 복사한 짧은 인용")


class ExtractedField(BaseModel, Generic[V]):
    status: FieldStatus
    value: V | None
    evidence: list[Evidence]

    @model_validator(mode="after")
    def _status_matches_value(self) -> Self:
        # 문서에 없다고 해 놓고 값을 채우는 '환각'과, 값만 있고 근거가 없는 응답을 거절한다.
        if self.status == "NOT_FOUND" and (self.value is not None or self.evidence):
            raise ValueError("NOT_FOUND requires value=null and evidence=[]")
        if self.status == "FOUND" and (self.value is None or not self.evidence):
            raise ValueError("FOUND requires a non-null value and at least one evidence")
        if self.status == "AMBIGUOUS" and not self.evidence:
            raise ValueError("AMBIGUOUS requires at least one evidence")
        return self


class Party(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(description="갑/을, 발주자/수급자 등 문서에 쓰인 역할")


class Money(BaseModel):
    amount: str = Field(pattern=r"^\d+(\.\d+)?$", description="쉼표 없는 숫자 문자열")
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 통화 코드 (원 → KRW)")


class ReviewItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    priority: Priority
    evidence: list[Evidence] = Field(min_length=1)


class ContractExtraction(BaseModel):
    contract_title: ExtractedField[str]
    parties: ExtractedField[list[Party]]
    start_date: ExtractedField[date]
    end_date: ExtractedField[date]
    contract_amount: ExtractedField[Money]
    auto_renewal: ExtractedField[str]
    termination: ExtractedField[str]
    penalty: ExtractedField[str]
    payment_terms: ExtractedField[str]
    confidentiality: ExtractedField[str]
    review_items: list[ReviewItem] = Field(max_length=10)


FIELD_NAMES: tuple[str, ...] = tuple(
    name for name in ContractExtraction.model_fields if name != "review_items"
)


# ---------- 검증 후 결과 ----------


class VerifiedEvidence(Evidence):
    verified: bool


class FieldResult(BaseModel, Generic[V]):
    status: FieldStatus
    value: V | None
    evidence: list[VerifiedEvidence]
    verification: Verification


class ReviewItemResult(BaseModel):
    item_id: str
    title: str
    reason: str
    priority: Priority
    evidence: list[VerifiedEvidence]
    verification: Verification


class DocumentStats(BaseModel):
    page_count: int
    char_count: int
    empty_pages: list[int]


class AnalysisResult(BaseModel):
    contract_title: FieldResult[str]
    parties: FieldResult[list[Party]]
    start_date: FieldResult[date]
    end_date: FieldResult[date]
    contract_amount: FieldResult[Money]
    auto_renewal: FieldResult[str]
    termination: FieldResult[str]
    penalty: FieldResult[str]
    payment_terms: FieldResult[str]
    confidentiality: FieldResult[str]
    review_items: list[ReviewItemResult]
    document_stats: DocumentStats
    warnings: list[str]
