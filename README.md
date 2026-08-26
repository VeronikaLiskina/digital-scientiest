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

## Выбор LLM-провайдера

Интерактивный RAG-ассистент и автоматический перевод поискового запроса могут
работать через локальную Ollama, Groq или гибрид обоих провайдеров. По умолчанию
остаётся локальный режим:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=gemma4:12b
```

Для Groq создайте новый ключ в Groq Console и сохраните его только в `.env`:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-120b
GROQ_REASONING_EFFORT=medium
GROQ_MAX_COMPLETION_TOKENS=1400
```

Гибридный режим сначала запускает Ollama. Если локальная модель не ответила за
заданный интервал, Groq получает тот же prompt и тот же RAG-контекст. Используется
первый успешно завершившийся ответ; при ошибке или исчерпании квоты Groq система
продолжает ждать уже выполняющийся локальный запрос:

```env
LLM_PROVIDER=hybrid
HYBRID_FALLBACK_DELAY_SECONDS=35
```

До переключения всего backend проверьте новый ключ отдельным коротким запросом:

```powershell
docker compose run --rm --build -e LLM_PROVIDER=groq backend `
  python -m scripts.check_groq_connection
```

После смены провайдера пересоздайте backend:

```powershell
docker compose up -d --build --force-recreate backend
```

В Groq передаются тот же RAG prompt и те же фрагменты публикаций, что и в
Ollama. Встроенные browser search, code execution и другие tools не включаются,
поэтому модель не получает внешние источники и сохраняется честность benchmark.
Для возврата к локальной модели достаточно снова указать
`LLM_PROVIDER=ollama` и пересоздать backend. AI-анализ метаданных публикаций —
отдельный внутренний процесс; он продолжает использовать Ollama.

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
дедупликации в строгую проверку релевантности передаются лучшие 20 чанков.
Прошедшие её фрагменты оценивает cross-encoder
`BAAI/bge-reranker-v2-m3`; в контекст LLM попадают не более 8 результатов с
нормализованной оценкой не ниже `RERANKER_MIN_SCORE`. Если ни один фрагмент не
прошёл любую из двух проверок, ассистент возвращает «недостаточно информации»
без вызова LLM.

Модель reranker настраивается переменными `RERANKER_MODEL_NAME`,
`RERANKER_BATCH_SIZE`, `RERANKER_MAX_LENGTH`, `RERANKER_MIN_SCORE` и
`RERANKER_TOP_K`. При первом содержательном запросе модель скачивается в общий
Hugging Face cache; пересоздавать embeddings после её смены не нужно.

FTS-индекс создаётся миграцией и обновляется PostgreSQL автоматически при
изменении `chunk_text`:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Для диагностики каждого запроса в backend-логе выводятся `vector_results`,
`full_text_results`, `rrf_results`, `reranked_chunks` и
`final_selected_chunks`.

## Evaluation production retrieval

В `backend/evaluation/retrieval_dataset.json` находится набор из 30 вручную
проверенных вопросов к реальным `document_chunks`: semantic, exact,
cross-language, no-answer и short/ambiguous. Один запуск сравнивает hybrid
RRF, relevance gate и reranker по Recall@5, Recall@10, MRR, answerability
accuracy, false positives и false negatives:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m scripts.evaluate_retrieval `
  --output evaluation/results.json
```

Для baseline без загрузки reranker-модели добавьте `--skip-reranker`.
