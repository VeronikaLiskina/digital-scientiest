import asyncio
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


async def test_background_processing_respects_concurrency_limit(monkeypatch):
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started: list[int] = []
    active_jobs = 0
    max_active_jobs = 0

    async def fake_process(source_file_id: int) -> None:
        nonlocal active_jobs, max_active_jobs
        started.append(source_file_id)
        active_jobs += 1
        max_active_jobs = max(max_active_jobs, active_jobs)

        try:
            if source_file_id == 1:
                first_started.set()
                await release_first.wait()
        finally:
            active_jobs -= 1

    monkeypatch.setattr(
        pdf_processing_queue,
        "_processing_slots",
        asyncio.BoundedSemaphore(1),
    )
    monkeypatch.setattr(
        pdf_processing_queue,
        "_run_source_file_processing",
        fake_process,
    )

    first_task = asyncio.create_task(
        pdf_processing_queue._process_source_file_in_background(1)
    )
    await first_started.wait()
    second_task = asyncio.create_task(
        pdf_processing_queue._process_source_file_in_background(2)
    )
    await asyncio.sleep(0)

    assert started == [1]
    assert max_active_jobs == 1

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert started == [1, 2]
    assert max_active_jobs == 1
