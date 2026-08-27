# Цифровой учёный

Веб-приложение для хранения и обработки научных публикаций, семантического
поиска и ответов на вопросы по загруженным материалам. Ассистент работает по
RAG-подходу: сначала находит подходящие фрагменты публикаций, проверяет их
релевантность и только затем передаёт контекст языковой модели.

## Возможности

- загрузка одной или нескольких PDF-публикаций;
- извлечение текста и метаданных, OCR для сканированных страниц;
- автоматическое разбиение текста на чанки и построение embeddings;
- каталог публикаций, авторов, тем и ключевых слов;
- семантический и полнотекстовый поиск;
- RAG-ассистент с точными ссылками на использованные фрагменты;
- автоматический поиск между русскими и английскими публикациями;
- локальная генерация через Ollama, облачная через Groq или гибридный режим;
- очередь фоновой обработки PDF и журнал ошибок;
- воспроизводимые retrieval- и model-evaluation тесты.

## Как устроен проект

```mermaid
flowchart LR
    UI[React-интерфейс] --> API[FastAPI]
    API --> DB[(PostgreSQL + pgvector)]
    API --> REDIS[(Redis)]
    REDIS --> WORKER[Celery worker]
    WORKER --> PDF[PDF / OCR / чанки / embeddings]
    PDF --> DB

    API --> SEARCH[Vector search + FTS + RRF]
    SEARCH --> GATE[Relevance gate]
    GATE --> RERANK[BGE reranker]
    RERANK --> LLM[Ollama / Groq / Hybrid]
    LLM --> UI
```

### Основные технологии

| Слой | Используется |
|---|---|
| Frontend | React 18, TypeScript, Vite, React Router, Sass |
| API | FastAPI, Pydantic, SQLAlchemy, Alembic |
| Хранилище | PostgreSQL 16, pgvector |
| Фоновые задачи | Celery, Redis |
| PDF и OCR | PyMuPDF, pypdf, Tesseract, pytesseract, Pillow |
| Embeddings | `intfloat/multilingual-e5-base`, Sentence Transformers |
| Reranker | `BAAI/bge-reranker-v2-m3`, Transformers, PyTorch |
| LLM | Ollama (`gemma4:12b`), Groq (`openai/gpt-oss-120b`) |
| Тестирование | pytest, Node.js test runner |

## Быстрый запуск

### Требования

- Docker Desktop с Docker Compose;
- Ollama, запущенная на основной системе;
- модель `gemma4:12b` для локального или гибридного режима;
- Groq API key — только если нужен `groq` или `hybrid`.

### 1. Подготовьте настройки

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

Реальный `GROQ_API_KEY` храните только в `.env`. Этот файл исключён из Git.

### 2. Подготовьте локальную модель

```powershell
ollama pull gemma4:12b
ollama list
```

Ollama должна продолжать работать во время использования ассистента. Docker
обращается к ней через `http://host.docker.internal:11434`.

### 3. Запустите приложение

```powershell
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

После запуска доступны:

- пользовательский интерфейс — <http://localhost:5173>;
- ассистент — <http://localhost:5173/assistant>;
- административная часть — <http://localhost:5173/admin>;
- API — <http://localhost:8000>;
- Swagger UI — <http://localhost:8000/docs>;
- проверка состояния — <http://localhost:8000/health>.

Проверить контейнеры и логи:

```powershell
docker compose ps
docker compose logs -f backend celery-worker
```

Остановить приложение без удаления базы:

```powershell
docker compose down
```

> `docker compose down -v` удаляет тома PostgreSQL и Redis вместе с данными.

## Как работает AI-ассистент

Для каждого вопроса выполняется следующий конвейер:

1. `multilingual-e5-base` строит embedding вопроса.
2. pgvector возвращает до 50 семантических кандидатов, PostgreSQL FTS — до
   50 лексических кандидатов.
3. Reciprocal Rank Fusion (`RRF_K=60`) объединяет результаты и оставляет до
   30 чанков.
4. Relevance gate отбрасывает фрагменты без достаточных текстовых или
   семантических признаков.
5. Cross-encoder `bge-reranker-v2-m3` переоценивает оставшиеся пары
   «вопрос — фрагмент». В итоговый контекст попадает не более 6 чанков с
   оценкой не ниже `0.5`.
6. Если первый поиск слабый, вопрос автоматически переводится на другой язык
   и выполняется дополнительный поиск. Это позволяет задавать русские вопросы
   к английским статьям и наоборот. При сильном первом результате повторный
   поиск пропускается.
7. LLM получает только проверенные фрагменты. Ответ проходит валидацию языка,
   JSON-структуры и ссылок на реально использованные `chunk_id`.

Если надёжных источников нет, система возвращает сообщение о недостатке
информации и не просит модель придумывать ответ.

## Выбор LLM-провайдера

Провайдер задаётся в `.env` через `LLM_PROVIDER`.

| Режим | Поведение | Особенности |
|---|---|---|
| `ollama` | Все ответы генерируются локально | Максимальная приватность, скорость зависит от компьютера |
| `groq` | Все ответы генерируются через Groq API | Обычно быстрее, но требуется сеть и доступная квота |
| `hybrid` | Сначала запускается Ollama, через 10 секунд — Groq | Ограничивает очень долгие локальные ответы |

### Только Ollama

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gemma4:12b
OLLAMA_NUM_CTX=8192
OLLAMA_THINK=false
```

### Только Groq

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-120b
GROQ_REASONING_EFFORT=medium
GROQ_MAX_COMPLETION_TOKENS=1400
```

Проверить ключ до переключения основного backend:

```powershell
docker compose run --rm -e LLM_PROVIDER=groq backend `
  python -m scripts.check_groq_connection
```

### Гибридный режим

```env
LLM_PROVIDER=hybrid
HYBRID_FALLBACK_DELAY_SECONDS=10
```

В этом режиме Ollama запускается первой. Если она не завершила генерацию за
10 секунд, параллельно запускается Groq; используется первый корректный ответ.
Если Groq недоступен или исчерпал квоту, система продолжает ждать локальную
модель.

После изменения `.env` пересоздайте backend:

```powershell
docker compose up -d --force-recreate backend
```

### Приватность

В режиме `ollama` вопрос и контекст не покидают компьютер. В режимах `groq` и
`hybrid` Groq может получить вопрос, системный prompt и выбранные RAG-фрагменты.
Browser search, code execution и другие внешние tools в проекте не включены.

AI-анализ метаданных PDF является отдельным процессом и использует Ollama даже
при облачном провайдере интерактивного ассистента.

## Обработка публикаций

После загрузки PDF система:

1. проверяет тип, размер и хеш файла;
2. извлекает метаданные и предлагает совпадения из справочников;
3. отправляет подтверждённую публикацию в Celery;
4. извлекает текст, при необходимости запускает OCR;
5. строит смысловые чанки и embeddings;
6. сохраняет результаты и статус обработки в PostgreSQL.

В очередь передаётся только `source_file_id`. Сам PDF читается worker из общего
каталога `backend/uploads`. Redis используется как брокер задач, а состояние и
ошибки сохраняются в PostgreSQL. Celery Beat проекту не требуется.

Ограничения массовой загрузки: не более 20 PDF за запрос, до 50 МБ на один файл
и до 300 МБ на пакет.

## Настройки поиска

Основные переменные находятся в `.env.example`.

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `EMBEDDING_MODEL_NAME` | `intfloat/multilingual-e5-base` | Модель embeddings |
| `RERANKER_MODEL_NAME` | `BAAI/bge-reranker-v2-m3` | Cross-encoder reranker |
| `RERANKER_MAX_LENGTH` | `768` | Максимальная длина пары для reranker |
| `RERANKER_MIN_SCORE` | `0.5` | Минимальная оценка релевантности |
| `RERANKER_TOP_K` | `6` | Максимум чанков в RAG-контексте |
| `HYBRID_FALLBACK_DELAY_SECONDS` | `10` | Задержка запуска Groq в hybrid |

После первой установки embedding- и reranker-модели скачиваются в общий Docker
том `huggingface_cache`. Поэтому первый содержательный запрос может быть заметно
дольше последующих.

### Смена embedding-модели

После изменения `EMBEDDING_MODEL_NAME` необходимо перестроить векторы всех
чанков:

```powershell
docker compose exec backend python -m app.scripts.rebuild_embeddings
```

Скрипт удаляет векторы другой модели, поэтому поиск не смешивает embeddings от
разных моделей. При смене только reranker перестраивать embeddings не нужно.

## Разработка без полного Docker Compose

Базу и Redis можно оставить в Docker:

```powershell
docker compose up -d db redis
```

Создайте виртуальное окружение и установите backend-зависимости:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DATABASE_URL = "postgresql+asyncpg://postgres:nika@localhost:55432/digital_scientist"
$env:CELERY_BROKER_URL = "redis://localhost:6379/0"
```

API:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Celery worker в отдельном терминале:

```powershell
Set-Location backend
..\.venv\Scripts\celery.exe -A app.celery_app:celery_app worker --loglevel=INFO
```

Frontend в отдельном терминале:

```powershell
Set-Location frontend
npm install
npm run dev
```

## Тестирование

Backend:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Frontend:

```powershell
Set-Location frontend
npm test
npm run build
```

## Evaluation и отчёты

Retrieval-набор находится в
[`backend/benchmarks/retrieval_dataset.json`](backend/benchmarks/retrieval_dataset.json)
и содержит 31 вручную проверенный вопрос категорий `semantic`, `exact`,
`cross_language`, `no_answer` и `short_ambiguous`.

Полный прогон vector search, FTS, RRF, relevance gate и reranker:

```powershell
docker compose exec backend python -m scripts.evaluate_retrieval
```

Для быстрого baseline без reranker:

```powershell
docker compose exec backend python -m scripts.evaluate_retrieval --skip-reranker
```

Сравнение embedding-моделей:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m benchmarks.compare_embedding_models `
  --output benchmarks/results.json
```

Итоговое историческое сравнение LLM доступно в
[`backend/evaluation/final_model_comparison_report.html`](backend/evaluation/final_model_comparison_report.html).
В нём зафиксирована конфигурация на момент benchmark, включая прежнюю задержку
Groq fallback 35 секунд; текущая рабочая настройка — 10 секунд.

## Структура репозитория

```text
digital-scientiest/
├── backend/
│   ├── app/                 # FastAPI, модели, поиск, RAG и фоновые задачи
│   ├── migrations/          # миграции Alembic
│   ├── benchmarks/          # фиксированные retrieval-наборы
│   ├── evaluation/          # итоговый отчёт сравнения моделей
│   ├── scripts/             # диагностические и evaluation-команды
│   └── tests/               # backend-тесты
├── frontend/
│   ├── src/                 # React-приложение
│   └── tests/               # frontend-тесты
├── exports/                 # подготовленные выгрузки данных
├── docker-compose.yml
├── .env.example
└── README.md
```

## Частые проблемы

### Ассистент не подключается к Ollama

Проверьте, что Ollama запущена и модель установлена:

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Для Docker значение `OLLAMA_BASE_URL` должно быть
`http://host.docker.internal:11434`.

### Первый вопрос отвечает очень долго

При первом запросе загружаются embedding-модель, reranker и LLM. Повторный
запрос обычно быстрее. Посмотреть происходящее можно командой:

```powershell
docker compose logs -f backend
```

### После смены `.env` ничего не изменилось

Пересоздайте контейнер:

```powershell
docker compose up -d --force-recreate backend celery-worker
```

### База не соответствует текущему коду

Примените все миграции:

```powershell
docker compose exec backend alembic upgrade head
```

### PDF остаётся в очереди

Проверьте Redis и worker:

```powershell
docker compose ps redis celery-worker
docker compose logs --tail 200 celery-worker
```
