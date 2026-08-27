from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.source_file import SourceFile
from app.utils.file_hash import calculate_file_hash


class PdfStorageService:
    """Validate, deduplicate and persist uploaded PDF files."""

    def __init__(self, upload_dir: str | Path) -> None:
        self.upload_dir = Path(upload_dir)

    @staticmethod
    def validate_upload(file: UploadFile) -> str:
        original_name = file.filename or "publication.pdf"
        if Path(original_name).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")
        return original_name

    def save_content(self, content: bytes) -> Path:
        if not content:
            raise HTTPException(status_code=400, detail="Файл пустой")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        saved_path = self.upload_dir / f"{uuid4()}.pdf"
        saved_path.write_bytes(content)
        return saved_path

    @staticmethod
    async def find_by_hash(
        db: AsyncSession,
        file_hash: str,
    ) -> SourceFile | None:
        result = await db.execute(
            select(SourceFile).where(SourceFile.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def save_upload(
        self,
        db: AsyncSession,
        file: UploadFile,
        *,
        comment: str | None = None,
        fail_on_duplicate: bool = True,
    ) -> tuple[SourceFile, bool]:
        original_name = self.validate_upload(file)
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Файл пустой")

        file_hash = calculate_file_hash(content)
        existing_file = await self.find_by_hash(db, file_hash)
        if existing_file is not None:
            if fail_on_duplicate:
                raise HTTPException(status_code=409, detail="Такой PDF уже загружался")
            return existing_file, True

        saved_path = self.save_content(content)
        source_file = SourceFile(
            file_name=original_name,
            file_path=str(saved_path),
            file_type="application/pdf",
            file_hash=file_hash,
            pdf_quality="text_pdf",
            has_figures=False,
            has_tables=False,
            processing_status="new",
            comment=comment,
        )
        db.add(source_file)
        await db.flush()
        return source_file, False


def _default_storage() -> PdfStorageService:
    return PdfStorageService(settings.upload_dir)


def validate_pdf_upload(file: UploadFile) -> str:
    return PdfStorageService.validate_upload(file)


def save_pdf_content(original_name: str, content: bytes) -> Path:
    # Keep the original public signature for existing API callers.
    del original_name
    return _default_storage().save_content(content)


async def find_source_file_by_hash(
    db: AsyncSession,
    file_hash: str,
) -> SourceFile | None:
    return await PdfStorageService.find_by_hash(db, file_hash)


async def save_uploaded_pdf_as_source_file(
    db: AsyncSession,
    file: UploadFile,
    *,
    comment: str | None = None,
    fail_on_duplicate: bool = True,
) -> tuple[SourceFile, bool]:
    return await _default_storage().save_upload(
        db,
        file,
        comment=comment,
        fail_on_duplicate=fail_on_duplicate,
    )
