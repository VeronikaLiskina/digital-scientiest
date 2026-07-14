from types import SimpleNamespace

import pytest

from app.services import pdf_processing_queue
from app.services.publication_status_service import status_for_pdf_state


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


class StubSession:
    def __init__(self, source_file) -> None:
        self.source_file = source_file
        self.commit_count = 0

    async def get(self, _model, _source_file_id):
        return self.source_file

    async def commit(self) -> None:
        self.commit_count += 1


def test_publication_status_follows_pdf_state():
    assert status_for_pdf_state("processed", 3) == "processed"
    assert status_for_pdf_state("processed", 0) == "review"
    assert status_for_pdf_state("processing", 0) == "review"
    assert status_for_pdf_state("error", 0) == "review"


async def test_enqueue_pdf_processing_marks_file_queued_before_start(monkeypatch):
    source_file = SimpleNamespace(processing_status="requires_review")
    db = StubSession(source_file)
    started: list[int] = []
    monkeypatch.setattr(
        pdf_processing_queue,
        "_start_processing_task",
        started.append,
    )

    status = await pdf_processing_queue.enqueue_pdf_processing(
        db,
        42,
        skip_processed=True,
    )

    assert status == "queued"
    assert source_file.processing_status == "queued"
    assert db.commit_count == 1
    assert started == [42]


@pytest.mark.parametrize("processing_status", ["queued", "processing", "processed"])
async def test_automatic_enqueue_does_not_start_duplicate_processing(
    monkeypatch,
    processing_status,
):
    source_file = SimpleNamespace(processing_status=processing_status)
    db = StubSession(source_file)
    started: list[int] = []
    monkeypatch.setattr(
        pdf_processing_queue,
        "_start_processing_task",
        started.append,
    )

    status = await pdf_processing_queue.enqueue_pdf_processing(
        db,
        42,
        skip_processed=True,
    )

    assert status == processing_status
    assert db.commit_count == 0
    assert started == []
