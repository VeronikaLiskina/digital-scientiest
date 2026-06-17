import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.database import Base, get_db

# Импортируем модели, чтобы SQLAlchemy знал, какие таблицы создавать
from app.models.author import Author  # noqa: F401
from app.models.topic import Topic  # noqa: F401
from app.models.keyword import Keyword  # noqa: F401
from app.models.publication import Publication  # noqa: F401
from app.models.source_file import SourceFile  # noqa: F401
from app.models.document_chunk import DocumentChunk  # noqa: F401
from app.models.processing_log import ProcessingLog  # noqa: F401


TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:nika@127.0.0.1:5432/digital_scientist_test"
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"ssl": False},
    poolclass=NullPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def prepare_test_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()