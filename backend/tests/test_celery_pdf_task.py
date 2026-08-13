from types import SimpleNamespace

import httpx
import pytest

from app.tasks import pdf_processing as pdf_task


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


class ScalarResult:
    def scalar_one_or_none(self):
        return None


class WorkerSession:
    def __init__(self, source_file) -> None:
        self.source_file = source_file
        self.commit_count = 0
        self.lock_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None

    async def get(self, _model, _object_id):
        return self.source_file

    async def refresh(self, _instance, *, with_for_update=False):
        self.lock_count += int(with_for_update)

    async def commit(self):
        self.commit_count += 1

    async def execute(self, _query):
        return ScalarResult()


def worker_source(status="queued", task_id="task-42"):
    return SimpleNamespace(
        processing_status=status,
        processing_task_id=task_id,
    )


async def test_worker_uses_own_session_and_existing_pipeline(monkeypatch):
    source_file = worker_source()
    session = WorkerSession(source_file)
    embedding_service = object()
    pipeline_calls: list[tuple[object, int, object, str]] = []

    monkeypatch.setattr(pdf_task, "async_session_maker", lambda: session)
    monkeypatch.setattr(
        pdf_task,
        "_get_worker_embedding_service",
        lambda: embedding_service,
    )

    async def process_pdf_file(*, db, source_file_id, embedding_service):
        pipeline_calls.append(
            (db, source_file_id, embedding_service, source_file.processing_status)
        )
        source_file.processing_status = "completed"
        return {"source_file_id": source_file_id, "status": "completed"}

    monkeypatch.setattr(pdf_task, "process_pdf_file", process_pdf_file)

    result = await pdf_task._claim_and_process_pdf(42, "task-42")

    assert result == {"source_file_id": 42, "status": "completed"}
    assert pipeline_calls == [(session, 42, embedding_service, "processing")]
    assert source_file.processing_task_id == "task-42"
    assert session.lock_count == 1


async def test_worker_skips_completed_file_without_duplicate_chunks(monkeypatch):
    source_file = worker_source(status="completed")
    session = WorkerSession(source_file)
    pipeline_calls: list[int] = []

    monkeypatch.setattr(pdf_task, "async_session_maker", lambda: session)

    async def process_pdf_file(**_kwargs):
        pipeline_calls.append(1)

    monkeypatch.setattr(pdf_task, "process_pdf_file", process_pdf_file)

    result = await pdf_task._claim_and_process_pdf(42, "task-42")

    assert result == {
        "source_file_id": 42,
        "status": "completed",
        "skipped": True,
    }
    assert pipeline_calls == []


async def test_worker_persists_retry_and_failure_statuses(monkeypatch):
    source_file = worker_source(status="processing")
    session = WorkerSession(source_file)
    logs: list[dict] = []

    monkeypatch.setattr(pdf_task, "async_session_maker", lambda: session)

    async def record_log(**kwargs):
        logs.append(kwargs)

    monkeypatch.setattr(pdf_task, "add_processing_log", record_log)

    await pdf_task._mark_task_for_retry(
        42,
        "task-42",
        TimeoutError("database timeout"),
    )
    assert source_file.processing_status == "queued"
    assert logs[-1]["step_name"] == "processing_retry_scheduled"

    await pdf_task._mark_task_failed(42, "task-42", ValueError("bad PDF"))
    assert source_file.processing_status == "failed"
    assert logs[-1]["step_name"] == "processing_worker_failed"
    assert logs[-1]["error_message"] == "bad PDF"


def test_only_temporary_errors_are_classified_for_retry():
    assert pdf_task.is_temporary_processing_error(TimeoutError("timeout"))
    assert pdf_task.is_temporary_processing_error(ConnectionError("connection"))
    assert pdf_task.is_temporary_processing_error(
        httpx.ConnectError("network unavailable")
    )
    assert not pdf_task.is_temporary_processing_error(ValueError("invalid PDF"))


def test_celery_task_retries_temporary_error(monkeypatch):
    retry_calls: list[tuple[BaseException, int]] = []

    class RetryRequested(Exception):
        pass

    def run_async(coroutine):
        coroutine_name = coroutine.cr_code.co_name
        coroutine.close()
        if coroutine_name == "_claim_and_process_pdf":
            raise TimeoutError("temporary")
        return None

    def retry(*, exc, countdown):
        retry_calls.append((exc, countdown))
        raise RetryRequested

    monkeypatch.setattr(pdf_task, "_run_async", run_async)
    monkeypatch.setattr(pdf_task.process_pdf_task, "retry", retry)

    with pytest.raises(RetryRequested):
        pdf_task.process_pdf_task.run(42)

    assert len(retry_calls) == 1
    assert isinstance(retry_calls[0][0], TimeoutError)


def test_celery_task_does_not_retry_permanent_error(monkeypatch):
    retry_calls: list[BaseException] = []

    def run_async(coroutine):
        coroutine_name = coroutine.cr_code.co_name
        coroutine.close()
        if coroutine_name == "_claim_and_process_pdf":
            raise ValueError("invalid PDF")
        return None

    def retry(*, exc, countdown):
        retry_calls.append(exc)

    monkeypatch.setattr(pdf_task, "_run_async", run_async)
    monkeypatch.setattr(pdf_task.process_pdf_task, "retry", retry)

    with pytest.raises(ValueError, match="invalid PDF"):
        pdf_task.process_pdf_task.run(42)

    assert retry_calls == []


def test_embedding_service_is_loaded_once_per_worker_process(monkeypatch):
    created: list[object] = []

    def create_embedding_service():
        instance = object()
        created.append(instance)
        return instance

    pdf_task._get_worker_embedding_service.cache_clear()
    monkeypatch.setattr(pdf_task, "get_embedding_service", create_embedding_service)

    try:
        first = pdf_task._get_worker_embedding_service()
        second = pdf_task._get_worker_embedding_service()
    finally:
        pdf_task._get_worker_embedding_service.cache_clear()

    assert first is second
    assert len(created) == 1
