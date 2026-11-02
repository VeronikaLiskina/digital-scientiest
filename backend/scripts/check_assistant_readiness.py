"""Read-only readiness check for transferring the assistant to another PC.

Does not download models or send publication contents to an external service.
--check-api sends only a short synthetic connection test to the selected API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, or_, select, text

from app.core.config import settings
from app.db.database import async_session_maker, engine
from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.services.llm.base import LocalLLMError
from app.services.llm.factory import create_http_llm_provider


def cached_model_ready(model_name: str) -> bool:
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        snapshot = Path(snapshot_download(model_name, local_files_only=True))
    except (LocalEntryNotFoundError, OSError, ValueError):
        return False
    weights = list(snapshot.glob("*.safetensors")) + list(snapshot.glob("pytorch_model*.bin"))
    return (snapshot / "config.json").is_file() and any(path.is_file() for path in weights)


async def inspect_database() -> dict:
    async with async_session_maker() as db:
        statuses = dict((await db.execute(select(Publication.status, func.count()).group_by(Publication.status))).all())
        total_chunks = int((await db.execute(select(func.count(DocumentChunk.id)))).scalar_one())
        unsearchable = int((await db.execute(select(func.count(DocumentChunk.id)).where(or_(
            DocumentChunk.embedding.is_(None), DocumentChunk.embedding_model.is_(None),
            DocumentChunk.embedding_model != settings.embedding_model_name,
        )))).scalar_one())
        without_chunks = list((await db.execute(select(Publication.id).where(~Publication.chunks.any()))).scalars())
        missing_pdf_ids = [file_id for file_id, path in (await db.execute(select(SourceFile.id, SourceFile.file_path))).all()
                           if not Path(path.replace("\\", "/")).is_file()]
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    return {"migration": version, "publications": sum(statuses.values()), "statuses": statuses,
            "chunks": total_chunks, "unsearchable_chunks": unsearchable,
            "publications_without_chunks": without_chunks, "missing_pdf_ids": missing_pdf_ids}


async def inspect(check_api: bool) -> dict:
    report = {"provider": settings.llm_provider, "model": settings.active_llm_model, "issues": []}
    try:
        database = await inspect_database()
        report["database"] = database
        for field in ("unsearchable_chunks", "publications_without_chunks", "missing_pdf_ids"):
            if database[field]:
                report["issues"].append(field)
        if not database["publications"]:
            report["issues"].append("empty_catalog")
        if any(count for status, count in database["statuses"].items() if status != "processed"):
            report["issues"].append("publications_not_processed")
    except Exception as exc:
        # Database connection errors may contain credentials in their messages.
        report["database"] = {"error_type": type(exc).__name__}
        report["issues"].append("database_unavailable")
    finally:
        await engine.dispose()
    report["cached_models"] = {name: cached_model_ready(name) for name in {
        settings.embedding_model_name, settings.reranker_model_name,
    }}
    if not all(report["cached_models"].values()):
        report["issues"].append("search_models_not_cached")
    try:
        provider = create_http_llm_provider(timeout_seconds=30)
        report["api"] = {"configured": True, "checked": check_api}
        if check_api:
            await provider.generate("Reply with the single word READY.", system_prompt="Connection test. No tools.")
            report["api"]["reachable"] = True
    except LocalLLMError as exc:
        report["api"] = {"checked": check_api, "error_type": type(exc).__name__}
        report["issues"].append("api_unavailable" if check_api else "api_not_configured")
    from app.celery_app import celery_app
    try:
        workers = await asyncio.to_thread(celery_app.control.ping, timeout=3)
        report["pdf_worker_available"] = bool(workers)
    except Exception:
        report["pdf_worker_available"] = False
    if not report["pdf_worker_available"]:
        report["issues"].append("pdf_worker_unavailable")
    report["ready"] = not report["issues"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-api", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(inspect(args.check_api))
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(output, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return int(not report["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
