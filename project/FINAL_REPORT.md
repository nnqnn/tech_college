# Отчет

Проект - Telegram dating bot с backend API, анкетами, рейтингом, очередью событий, кэшем, фоновыми задачами, фото и метриками

## Telegram bot

Файлы:

- bot/main.py
- bot/handlers.py
- bot/keyboards.py
- bot/api_client.py
- bot/config.py

Что сделано:

- бот запускается через python -m bot.main
- пользователь регистрируется по телеграм ID через /start
- есть меню с анкетой, просмотром других анкет и помощью
- анкета заполняется пошагово прямо в Telegram
- после заполнения анкеты пользователь может загрузить реальные фото
- бот отправляет фото в бэкенд, а бэкенд сохраняет его в S3 совместимое хранилище
- при просмотре анкет бот показывает первое фото анкеты, если оно есть
- лайк и пропуск отправляются в бэкенд
- при взаимном лайке бот сообщает пользователю о мэтче

## Backend API

Файлы:

- backend/main.py
- backend/schemas.py
- backend/config.py

Технология:

- FastAPI
- Pydantic

Что сделано:

- апи принимает запросы от телеграм бота
- есть регистрация пользователей
- есть CRUD для анкет
- есть выдача следующей анкеты через /api/v1/feed/{telegram_id}/next
- есть эндпоинт для лайка и пропуска /api/v1/interactions
- есть эндпоинты для фото анкеты
- есть эндпоинт /metrics для Prometheus
- ошибки апи возвращаются нормальными HTTP статусами, например 404, 409, 415

Эндпоинты для фото:

- POST /api/v1/profiles/{telegram_id}/photos
- GET /api/v1/profiles/{telegram_id}/photos
- GET /api/v1/photos/{photo_id}
- DELETE /api/v1/profiles/{telegram_id}/photos/{photo_id}

## PostgreSQL

Файл:

- backend/storage.py

Технология:

- PostgreSQL
- psycopg

Что хранится:

- пользователи и анкеты в таблице users
- фото анкет в таблице user_photos
- лайки и пропуски в таблице user_interactions
- рейтинг пользователей в отдельной таблице user_ratings

Что сделано по базе:

- таблицы создаются автоматически при старте бэкенда
- добавлены индексы для быстрых запросов по анкетам, взаимодействиям и рейтингу
- для лайков есть защита от повторной оценки одной и той же анкеты
- photos_count синхронизируется с реальными фото пользователя
- рейтинг хранится отдельно

## Рейтинг и ранжирование

Файлы:

- backend/ranking.py
- backend/storage.py

Что сделано:

- первичный рейтинг считает заполненность анкеты, основные поля, предпочтения и фото
- поведенческий рейтинг считает лайки, пропуски, соотношение лайков и пропусков, взаимные лайки и активность
- комбинированный рейтинг собирает primary, behavioral и referral score
- реферальный фактор учитывается через referral_telegram_id
- выдача анкет сортируется по итоговому рейтингу
- уже оцененные анкеты не показываются повторно
- пользователь не видит свою анкету в ленте

Формула итогового рейтинга:

```text
total_score = 0.55 * primary_score + 0.35 * behavioral_score + 0.10 * referral_score
```

## Redis cache

Файлы:

- backend/cache.py
- backend/main.py

Технология:

- Redis

Что сделано:

- бэкенд кэширует пачку кандидатов для просмотра
- ключ кэша имеет формат candidates:{telegram_id}
- первая анкета берется после полного отбора и сортировки
- остальные анкеты из пачки кладутся в Redis
- при лайке, изменении анкеты или фото кэш очищается
- если Redis пачка закончилась, бэкенд собирает новую пачку из PostgreSQL

## RabbitMQ

Файлы:

- backend/events.py
- worker/main.py
- docker-compose.yml

Технология:

- RabbitMQ
- pika

Что сделано:

- бэкенд публикует события в очередь dating.events
- событие FeedRequested создается при выдаче анкеты
- событие InteractionCreated создается при лайке или пропуске
- отдельный consumer в worker/main.py может читать события и писать их в лог
- RabbitMQ также используется как broker для Celery

## Celery

Файлы:

- worker/celery_app.py
- backend/rating_jobs.py
- backend/main.py

Технология:

- Celery
- RabbitMQ как broker
- Redis как result backend

Что сделано:

- dating.refresh_user_rating пересчитывает рейтинг одного пользователя
- dating.refresh_all_ratings пересчитывает рейтинг всех пользователей
- dating.process_interaction_event пересчитывает рейтинг двух пользователей после взаимодействия
- Celery Beat регулярно запускает полный пересчет рейтингов
- бэкенд ставит задачи после изменения анкеты, фото и лайков
- если Celery недоступен, бэкенд делает синхронный пересчет, чтобы бот не ломался во время локального запуска

## S3 и MinIO

Файлы:

- backend/object_storage.py
- backend/main.py
- docker-compose.yml

Технология:

- MinIO
- boto3
- S3 compatible storage

Что сделано:

- реальные фото не хранятся в PostgreSQL
- бэкенд сохраняет файл в MinIO
- в базе хранится только s3_key, тип файла, размер и порядок фото
- для тестов есть InMemoryObjectStorage
- при удалении фото запись удаляется из базы, а объект удаляется из хранилища
- при удалении анкеты фото пользователя тоже очищаются

## Метрики и логи

Файлы:

- backend/metrics.py
- backend/logging_config.py
- worker/celery_app.py
- observability/prometheus.yml
- observability/grafana/provisioning/datasources/prometheus.yml
- observability/grafana/provisioning/dashboards/json/dating-overview.json

Технологии:

- Prometheus
- Grafana
- prometheus-client
- python-json-logger

Что сделано:

- бэкенд отдает метрики на /metrics
- считаются HTTP запросы и latency
- считаются feed requests
- считаются cache hit и cache miss
- считаются лайки, пропуски и мэтчи
- считаются загрузки и удаления фото
- считаются Celery enqueue и fallback пересчета рейтинга
- воркер отдает метрики на отдельном порту
- Grafana получает Prometheus datasource и готовый dashboard
- логи можно писать в json формате

## Docker Compose

Файл:

- docker-compose.yml

Что поднимается:

- backend
- PostgreSQL
- Redis
- RabbitMQ
- MinIO
- MinIO init для создания bucket
- Celery worker
- Celery beat
- Prometheus
- Grafana

## Тесты

Файлы:

- tests/conftest.py
- tests/test_registration.py
- tests/test_profiles_and_ranking.py
- tests/test_celery_tasks.py

Что проверяется:

- регистрация нового пользователя
- повторная регистрация существующего пользователя
- CRUD анкет
- создание рейтинга после сохранения анкеты
- реферальный рейтинг
- лайки, пропуски, защита от дублей и мэтчи
- публикация MQ события
- выдача анкет с фильтрацией и сортировкой
- Redis cache между запросами feed
- загрузка, список, скачивание и удаление фото
- обновление photos_count
- наличие фото в ответе feed
- Prometheus metrics endpoint
- Celery задачи пересчета рейтинга

Команды проверки:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall backend bot worker tests
.venv/bin/python -m pip check
docker-compose config
```

## Дополнительный функционал

- реальные фото вместо ручного счетчика фото
- MinIO как S3 хранилище
- гибридный пересчет рейтинга через Celery с fallback
- Prometheus metrics для backend и worker
- Grafana dashboard
- структурированные json логи
- in-memory реализации хранилища, кэша, MQ и S3 для быстрых тестов без Docker

