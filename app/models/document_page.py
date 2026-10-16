import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentPage(Base):
    """정제된 페이지 텍스트. 인용문 원문 대조와 추출 결과 추적에 쓴다.

    계약서 원문이므로 문서 삭제 시 즉시 지운다(서비스에서 명시 삭제 + FK CASCADE).
    """

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("page_no >= 1", name="page_no_positive"),
        CheckConstraint("char_count >= 0", name="char_count_non_negative"),
    )
