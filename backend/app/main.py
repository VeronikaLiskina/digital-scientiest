from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.api import assistant, search
from app.services.pdf_processing_queue import recover_saved_imports_without_chunks
from app.services.publication_status_service import synchronize_publication_statuses


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await synchronize_publication_statuses()
    await recover_saved_imports_without_chunks()
    yield


app = FastAPI(
    title="Digital Scientist API",
    description="MVP научного блока проекта Цифровой учёный",
    version="0.1.0",
    lifespan=lifespan,
)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(assistant.router)
app.include_router(search.router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
    }
