import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.task import Task
from tests.factories import make_korean_pdf
from tests.fixtures.sample_contract import SAMPLE_CONTRACT_PAGES

DOCS = "/api/v1/documents"


def analyzed_document(client: TestClient, text: str | None = None) -> tuple[str, str]:
    """업로드 + Fake LLM 분석까지 끝낸 (document_id, analysis_id)."""
    pages = SAMPLE_CONTRACT_PAGES if text is None else [*SAMPLE_CONTRACT_PAGES[:2], text]
    response = client.post(
        DOCS, files={"file": ("c.pdf", make_korean_pdf(pages), "application/pdf")}
    )
    document_id = response.json()["id"]
    analysis = client.post(f"{DOCS}/{document_id}/analyses").json()
    assert client.get(f"/api/v1/analyses/{analysis['id']}").json()["status"] == "SUCCEEDED"
    return document_id, analysis["id"]


def create(client: TestClient, document_id: str, **body: Any) -> Any:
    return client.post(f"{DOCS}/{document_id}/tasks", json=body)


def patch(client: TestClient, task_id: str, **body: Any) -> Any:
    return client.patch(f"/api/v1/tasks/{task_id}", json=body)


# ---------- 생성 ----------


def test_create_user_task(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)

    response = create(
        client, document_id, title="해지 조항 법무팀 검토", assignee="kim", due_date="2026-12-01"
    )

    assert response.status_code == 201
    task = response.json()
    assert response.headers["Location"] == f"/api/v1/tasks/{task['id']}"
    assert task["status"] == "TODO"
    assert task["priority"] == "MEDIUM"
    assert task["source"] == "USER"
    assert task["source_analysis_id"] is None
    assert task["version"] == 1


def test_analysis_alone_never_creates_tasks(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    assert client.get(f"{DOCS}/{document_id}/tasks").json()["total"] == 0


def test_accept_ai_suggestion_prefills_from_review_item(client: TestClient) -> None:
    document_id, analysis_id = analyzed_document(client)

    response = create(
        client, document_id, source={"analysis_id": analysis_id, "review_item_id": "r1"}
    )

    assert response.status_code == 201
    task = response.json()
    assert task["source"] == "AI_SUGGESTION"
    assert task["source_analysis_id"] == analysis_id
    assert task["source_item_id"] == "r1"
    assert task["title"] == "갑의 일방적 해지권"
    assert task["priority"] == "HIGH"
    assert "을에게 불리" in task["description"]


def test_user_values_override_suggestion(client: TestClient) -> None:
    document_id, analysis_id = analyzed_document(client)

    task = create(
        client,
        document_id,
        title="해지권 협상 필요",
        priority="LOW",
        source={"analysis_id": analysis_id, "review_item_id": "r1"},
    ).json()

    assert (task["title"], task["priority"]) == ("해지권 협상 필요", "LOW")


def test_same_suggestion_cannot_be_accepted_twice(client: TestClient) -> None:
    document_id, analysis_id = analyzed_document(client)
    source = {"analysis_id": analysis_id, "review_item_id": "r1"}
    first = create(client, document_id, source=source).json()

    response = create(client, document_id, source=source)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "TASK_ALREADY_EXISTS"
    assert error["details"] == {"task_id": first["id"]}


def test_database_rejects_duplicate_suggestion(client: TestClient, db_session: Session) -> None:
    document_id, analysis_id = analyzed_document(client)
    for _ in range(2):
        db_session.add(
            Task(
                document_id=uuid.UUID(document_id),
                title="t",
                source="AI_SUGGESTION",
                source_analysis_id=uuid.UUID(analysis_id),
                source_item_id="r1",
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize(
    ("source", "status_code", "code"),
    [
        ({"review_item_id": "r99"}, 400, "REVIEW_ITEM_NOT_FOUND"),
        ({"analysis_id": str(uuid.UUID(int=1))}, 404, "ANALYSIS_NOT_FOUND"),
    ],
)
def test_invalid_suggestion_reference(
    client: TestClient, source: dict[str, str], status_code: int, code: str
) -> None:
    document_id, analysis_id = analyzed_document(client)
    ref = {"analysis_id": analysis_id, "review_item_id": "r1", **source}

    response = create(client, document_id, source=ref)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_suggestion_from_another_documents_analysis_is_rejected(client: TestClient) -> None:
    document_a, analysis_a = analyzed_document(client)
    document_b, _ = analyzed_document(client, text="다른 계약서 3페이지")

    response = create(
        client, document_b, source={"analysis_id": analysis_a, "review_item_id": "r1"}
    )

    assert response.status_code == 404
    assert document_a != document_b


def test_create_requires_title_for_user_task(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    assert create(client, document_id, assignee="kim").status_code == 422


def test_create_on_missing_document(client: TestClient) -> None:
    assert create(client, str(uuid.uuid4()), title="x").status_code == 404


# ---------- 조회 ----------


def test_list_filters(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    create(client, document_id, title="a", priority="HIGH", assignee="kim")
    create(client, document_id, title="b", priority="LOW", assignee="lee")
    done = create(client, document_id, title="c", assignee="kim").json()
    task = patch(client, done["id"], version=1, status="IN_PROGRESS").json()
    patch(client, done["id"], version=task["version"], status="DONE")

    def titles(**params: str) -> list[str]:
        body = client.get(f"{DOCS}/{document_id}/tasks", params=params).json()
        return [t["title"] for t in body["items"]]

    assert titles() == ["a", "b", "c"]
    assert titles(assignee="kim") == ["a", "c"]
    assert titles(priority="LOW") == ["b"]
    assert titles(status="DONE") == ["c"]


def test_get_unknown_task(client: TestClient) -> None:
    response = client.get(f"/api/v1/tasks/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# ---------- 수정 ----------


def test_complete_and_reopen_task(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토").json()

    task = patch(client, task["id"], version=1, status="IN_PROGRESS", assignee="kim").json()
    assert (task["status"], task["assignee"], task["version"]) == ("IN_PROGRESS", "kim", 2)

    task = patch(client, task["id"], version=2, status="DONE").json()
    assert task["status"] == "DONE"
    assert task["completed_at"] is not None

    task = patch(client, task["id"], version=3, status="IN_PROGRESS").json()
    assert task["completed_at"] is None
    assert task["version"] == 4


def test_invalid_transition_returns_422(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토").json()

    response = patch(client, task["id"], version=1, status="DONE")  # TODO → DONE 불가

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_STATE_TRANSITION"
    assert error["details"] == {"from": "TODO", "to": "DONE"}
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["version"] == 1


def test_stale_version_is_rejected(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토").json()
    patch(client, task["id"], version=1, assignee="kim")  # 다른 사용자가 먼저 수정

    response = patch(client, task["id"], version=1, assignee="lee")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "VERSION_CONFLICT"
    assert error["details"] == {"current_version": 2}
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["assignee"] == "kim"


def test_clearing_optional_fields(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토", assignee="kim", due_date="2026-12-01").json()

    task = patch(client, task["id"], version=1, assignee=None, due_date=None).json()

    assert (task["assignee"], task["due_date"]) == (None, None)


def test_no_op_update_does_not_bump_version(client: TestClient) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토", priority="HIGH").json()

    response = patch(client, task["id"], version=1, priority="HIGH")

    assert response.status_code == 200
    assert response.json()["version"] == 1


# ---------- 이력·삭제 ----------


def test_history_records_field_changes(client: TestClient) -> None:
    document_id, analysis_id = analyzed_document(client)
    task = create(
        client, document_id, source={"analysis_id": analysis_id, "review_item_id": "r1"}
    ).json()
    patch(client, task["id"], version=1, status="IN_PROGRESS", assignee="kim")

    events = client.get(f"/api/v1/tasks/{task['id']}/history").json()["items"]

    assert [e["action"] for e in events] == ["TASK_CREATED", "TASK_UPDATED"]
    assert events[0]["changes"]["source"] == "AI_SUGGESTION"
    assert events[1]["changes"] == {
        "status": {"from": "TODO", "to": "IN_PROGRESS"},
        "assignee": {"from": None, "to": "kim"},
    }
    document_actions = [
        e["action"]
        for e in client.get(f"{DOCS}/{document_id}/history", params={"limit": 100}).json()["items"]
    ]
    assert document_actions[-2:] == ["TASK_CREATED", "TASK_UPDATED"]


def test_tasks_of_deleted_document_are_hidden(client: TestClient, db_session: Session) -> None:
    document_id, _ = analyzed_document(client)
    task = create(client, document_id, title="검토").json()

    client.delete(f"{DOCS}/{document_id}")

    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert client.get(f"{DOCS}/{document_id}/tasks").status_code == 404
    # 행은 남아 있다 (영구 삭제 정책은 후속 작업)
    assert db_session.scalar(select(func.count()).select_from(Task)) == 1
