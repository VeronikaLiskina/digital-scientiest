from types import SimpleNamespace

import pytest

from app.services import pdf_processing_queue
from app.services.publication_status_service import status_for_pdf_state


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


class StubScalarResult:
    def scalar_one_or_none(self):
        return None


class StubSession:
    def __init__(self, source_file) -> None:
        self.source_file = source_file
        self.commit_count = 0
        self.flush_count = 0
        self.rollback_count = 0
        self.lock_count = 0

    async def get(self, _model, _source_file_id):
        return self.source_file

    async def refresh(self, _instance, *, with_for_update=False) -> None:
        self.lock_count += int(with_for_update)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def execute(self, _query):
        return StubScalarResult()


def source_file(status: str, task_id: str | None = None):
    return SimpleNamespace(
        processing_status=status,
        processing_task_id=task_id,
    )


def test_publication_status_follows_pdf_state():
    assert status_for_pdf_state("completed", 3) == "processed"
    assert status_for_pdf_state("completed", 0) == "review"
    assert status_for_pdf_state("processed", 3) == "processed"
    assert status_for_pdf_state("processing", 0) == "review"
    assert status_for_pdf_state("failed", 0) == "review"


async def test_enqueue_pdf_processing_persists_queued_state_and_celery_id(
    monkeypatch,
):
    stored_file = source_file("requires_review")
    db = StubSession(stored_file)
    delayed: list[int] = []

    def delay(source_file_id: int):
        delayed.append(source_file_id)
        return SimpleNamespace(id="celery-task-42")

    monkeypatch.setattr(
        pdf_processing_queue.process_pdf_task,
        "delay",
        delay,
    )

    result = await pdf_processing_queue.enqueue_pdf_processing(db, 42)

    assert result.task_id == "celery-task-42"
    assert result.source_file_id == 42
    assert result.status == "queued"
    assert stored_file.processing_status == "queued"
    assert stored_file.processing_task_id == "celery-task-42"
    assert db.lock_count == 1
    assert db.flush_count == 1
    assert db.commit_count == 1
    assert delayed == [42]


@pytest.mark.parametrize(
    ("processing_status", "expected_status"),
    [
        ("queued", "queued"),
        ("processing", "processing"),
        ("completed", "completed"),
        ("processed", "completed"),
    ],
)
async def test_enqueue_is_idempotent_for_active_and_completed_files(
    monkeypatch,
    processing_status,
    expected_status,
):
    stored_file = source_file(processing_status, "existing-task")
    db = StubSession(stored_file)
    delayed: list[int] = []
    monkeypatch.setattr(
        pdf_processing_queue.process_pdf_task,
        "delay",
        delayed.append,
    )

    result = await pdf_processing_queue.enqueue_pdf_processing(db, 42)

    assert result.task_id == "existing-task"
    assert result.status == expected_status
    assert db.flush_count == 0
    assert db.commit_count == 0
    assert delayed == []


async def test_enqueue_failure_is_stored_in_postgresql(monkeypatch):
    stored_file = source_file("requires_review")
    db = StubSession(stored_file)
    logged: list[dict] = []

    def unavailable(_source_file_id: int):
        raise ConnectionError("redis unavailable")

    async def record_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(
        pdf_processing_queue.process_pdf_task,
        "delay",
        unavailable,
    )
    monkeypatch.setattr(pdf_processing_queue, "add_processing_log", record_log)

    with pytest.raises(pdf_processing_queue.PdfProcessingQueueError):
        await pdf_processing_queue.enqueue_pdf_processing(db, 42)

    assert db.rollback_count == 1
    assert stored_file.processing_status == "failed"
    assert stored_file.processing_task_id is None
    assert db.commit_count == 1
    assert logged[0]["source_file_id"] == 42
    assert logged[0]["step_name"] == "processing_enqueue_failed"
    assert logged[0]["error_message"] == "redis unavailable"
