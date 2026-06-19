import asyncio
from pathlib import Path

from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.source_file import SourceFile
from app.utils.file_hash import calculate_file_hash


async def main() -> None:
    async with async_session_maker() as db:
        result = await db.execute(
            select(SourceFile).where(SourceFile.file_hash.is_(None))
        )
        source_files = result.scalars().all()

        for source_file in source_files:
            file_path = Path(source_file.file_path)

            if not file_path.exists():
                continue

            source_file.file_hash = calculate_file_hash(file_path.read_bytes())

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
