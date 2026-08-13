# Digital Scientist

## Запуск через Docker Compose

Скопируйте пример настроек и запустите PostgreSQL, Redis, API, Celery worker и
frontend:

```bash
cp .env.example .env
docker compose up --build
```

В отдельном терминале примените миграции:

```bash
docker compose exec backend alembic upgrade head
```

API доступен на `http://localhost:8000`, frontend — на
`http://localhost:5173`.

PDF передаётся worker только по `source_file_id`. Сам файл читается из общего
тома `backend/uploads`, статусы выполнения и ошибки сохраняются в PostgreSQL.
Redis используется только как брокер Celery; result backend не настроен.

## Локальный запуск

Для запуска вне Docker установите зависимости backend и укажите локальные
адреса PostgreSQL и Redis:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DATABASE_URL = "postgresql+asyncpg://postgres:nika@localhost:55432/digital_scientist"
$env:CELERY_BROKER_URL = "redis://localhost:6379/0"
```

Запустите API:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Запустите worker в отдельном терминале:

```powershell
Set-Location backend
..\.venv\Scripts\celery.exe -A app.celery_app:celery_app worker --loglevel=INFO
```

Celery Beat проекту не требуется.

## Проверка

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

Set-Location ..\frontend
npm.cmd test
npm.cmd run build
```

## Embedding-модели

Основная модель задаётся через `EMBEDDING_MODEL_NAME` и по умолчанию равна
`intfloat/multilingual-e5-base`. Для сравнения также поддерживается
`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`.

После первой установки или смены модели пересоздайте векторы всех чанков:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m app.scripts.rebuild_embeddings
```

В Docker команда эквивалентна:

```bash
docker compose exec backend python -m app.scripts.rebuild_embeddings
```

Скрипт сначала удаляет векторы другой модели, поэтому поиск никогда не
смешивает их. API дополнительно фильтрует чанки по активной модели.

Сравнение E5 и прежней модели на фиксированном наборе вопросов запускается так:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m benchmarks.compare_embedding_models `
  --output benchmarks/results.json
```

Отчёт содержит `Recall@5`, `Recall@10` и `MRR`. Первый запуск скачает обе
модели в Hugging Face cache и может занять несколько минут.

## Гибридный поиск

Поиск ассистента объединяет 30 результатов pgvector и 30 результатов
PostgreSQL Full Text Search через Reciprocal Rank Fusion (`k=60`). После
дедупликации в проверку релевантности передаются лучшие 20 чанков.

FTS-индекс создаётся миграцией и обновляется PostgreSQL автоматически при
изменении `chunk_text`:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Для диагностики каждого запроса в backend-логе выводятся `vector_results`,
`full_text_results`, `rrf_results` и `final_selected_chunks`.
