from fastapi import APIRouter

from app.api.authors import router as authors_router
from app.api.document_chunks import router as document_chunks_router
from app.api.keywords import router as keywords_router
from app.api.processing_logs import router as processing_logs_router
from app.api.publications import router as publications_router
from app.api.source_files import router as source_files_router
from app.api.topics import router as topics_router


api_router = APIRouter(prefix="/api")

api_router.include_router(authors_router)
api_router.include_router(topics_router)
api_router.include_router(keywords_router)
api_router.include_router(source_files_router)
api_router.include_router(publications_router)
api_router.include_router(document_chunks_router)
api_router.include_router(processing_logs_router)