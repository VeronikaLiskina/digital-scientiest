# Перенос «Цифрового учёного» на ПК института

Ассистент генерирует ответы через API, а поисковые модели `multilingual-e5-base`
и `bge-reranker-v2-m3` остаются локальными. Для научных ответов нужен доступ
к выбранному API из сети института. Подбор по каталогу работает без API.

## Что перенести

Нужны исходники проекта, рабочий `.env`, резервная копия PostgreSQL,
вся папка `backend/uploads` и Docker-том с кэшем Hugging Face.
Одна папка с кодом не содержит загруженных публикаций и базы данных.
Для запуска без повторной сборки можно дополнительно перенести Docker-образы
приложения. Архивы с образами и весами могут занимать несколько гигабайт.

Снимок базы создаётся на текущем ПК так:

```powershell
New-Item -ItemType Directory -Force exports/institute-transfer
docker compose exec -T db pg_dump -U postgres -d digital_scientist -Fc -f /tmp/institute.dump
docker cp digital_scientist_db:/tmp/institute.dump ./exports/institute-transfer/database.dump
Copy-Item -LiteralPath backend/uploads -Destination exports/institute-transfer/uploads -Recurse
```

Перед снимком дождитесь завершения импортов; во время копирования не загружайте
новые файлы. Проверяйте наличие PDF командой готовности ниже: файлы, отсутствующие
на исходном ПК, не появятся от переноса базы.

Том моделей можно сохранить без скачивания дополнительных образов:

```powershell
docker compose run --rm --no-deps -v "${PWD}/exports/institute-transfer:/transfer" backend python -c "import tarfile; archive=tarfile.open('/transfer/search-models.tar','w'); archive.add('/root/.cache/huggingface',arcname='huggingface'); archive.close()"
```

## Запуск на новом ПК

Установите Docker с поддержкой Linux-контейнеров, скопируйте проект и `.env`.
Скопируйте сохранённую папку `uploads` в `backend/uploads`. В `.env` адрес
PostgreSQL для контейнеров должен содержать хост `db`, Redis — `redis`.
Ключ API и провайдер должны соответствовать выбранному сервису.

Для **новой пустой базы** восстановите снимок до первого запуска приложения:

```powershell
docker compose up -d db redis
docker compose exec -T db pg_isready -U postgres -d digital_scientist
docker cp ./database.dump digital_scientist_db:/tmp/institute.dump
docker compose exec -T db pg_restore -U postgres -d digital_scientist --no-owner /tmp/institute.dump
```

Команда `pg_isready` должна подтвердить готовность базы перед восстановлением.
Для существующей установки используйте отдельную базу или сначала сохраните
её резервную копию; этот порядок рассчитан на чистую установку.

Если переносите кэш весов, положите `search-models.tar` в `exports/institute-transfer`
и восстановите **собственный архив**, созданный приведённой выше командой:

```powershell
docker compose build backend celery-worker frontend
docker compose run --rm --no-deps -v "${PWD}/exports/institute-transfer:/transfer" backend python -c "import tarfile; archive=tarfile.open('/transfer/search-models.tar'); archive.extractall('/root/.cache',filter='data'); archive.close()"
docker compose run --rm --no-deps backend alembic upgrade head
docker compose up -d
```

При первом запуске без перенесённого кэша поисковые модели будут загружены
при обращении к научному поиску. Если используете сохранённые Docker-образы,
загрузите их вместо сборки; их имена должны соответствовать именам в Compose.

База и Redis имеют проверки готовности; backend и воркер ждут их запуска.
Контейнеры настроены на перезапуск. PDF обрабатываются одним воркером с одной
взятой заранее задачей, CPU-параллелизм моделей ограничен настройками `.env`.
Каталог не загружает поисковые модели. Первый научный запрос после запуска
загружает их в память и может занять заметно больше времени.

## Проверка на месте

```powershell
docker compose ps
docker compose exec -T backend python -m scripts.check_assistant_readiness --check-api
```

В отчёте должны отсутствовать проблемы с PDF, обработкой, эмбеддингами,
кэшем моделей, воркером и API. `ready=true` означает техническую готовность
по перечисленным проверкам, а качество научных ответов проверяется отдельно.
Затем откройте <http://localhost:5173> и проверьте один подбор и один научный
вопрос с переходом по ссылке на источник.

## После добавления 50 публикаций

1. Дождитесь статуса `processed` у новых публикаций и проверьте команду готовности.
2. Повторите HTTP-проверку из README, сохранив отчёт под новым именем.
3. Добавьте контрольные вопросы по новым публикациям: точные факты, методы,
   тематический подбор, сочетания условий и вопросы без ответа.
4. Сравните качество и длительность по тем же вопросам до и после загрузки;
   сначала сравнивайте успешность, затем скорость. Время первого запроса
   включает загрузку моделей, а повторные запросы могут использовать кэш оценок.

Набор текущего архива привязан к ID публикаций. Если база переносится снимком,
ID сохранятся. При создании нового каталога вопросы и ожидаемые ID нужно обновить.
Процент успешности этого набора не означает такую же точность на любых вопросах.
