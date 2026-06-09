from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings


app = FastAPI(
    title="Digital Scientist API",
    description="MVP научного блока проекта Цифровой учёный",
    version="0.1.0",
)

app.include_router(api_router)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database_url_exists": bool(settings.database_url),
    }