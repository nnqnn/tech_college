# Dating backend

Проект содержит Telegram-бота и Backend API для регистрации, анкет, ранжирования и просмотра анкет.

## Документация
- `docs/services.md` — сервисы и их ответственность
- `docs/architecture.md` — схема взаимодействия компонентов
- `docs/database.md` — схема БД и правила рейтинга/кэша

## Что реализовано
- Telegram-бот:
  - `/start` и `/help`
  - регистрация по Telegram ID
  - просмотр своей анкеты
  - пошаговое заполнение анкеты
  - загрузка реальных фото анкеты из Telegram
  - перезаполнение и удаление анкеты
  - просмотр анкет
  - показ первого фото анкеты, если оно загружено
  - лайк/пропуск и сообщение о взаимном лайке
- Backend API:
  - регистрация пользователей
  - CRUD анкет
  - загрузка, выдача, список и удаление фото через S3/MinIO
  - события лайк/пропуск
  - публикация событий `InteractionCreated` и `FeedRequested` в RabbitMQ
  - постановка задач пересчета рейтинга в Celery с синхронным fallback
  - рейтинг в отдельной таблице `user_ratings`
  - выдача следующей анкеты с Redis-кэшем `candidates:{telegram_id}`
  - Prometheus-метрики на `/metrics`
- Инфраструктура:
  - PostgreSQL для пользователей, анкет, взаимодействий и рейтингов
  - Redis для кэша пачек кандидатов
  - RabbitMQ для очереди событий
  - MinIO для изображений
  - Celery worker/beat для фоновых пересчетов
  - Prometheus и Grafana для наблюдаемости
  - `docker-compose.yml` для локального запуска всей связки

## Быстрый старт
1. Установить зависимости:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Создать `.env` на основе `.env.example`.
3. Запустить инфраструктуру:
   - `docker compose up -d`
   - если установлен старый Compose: `docker-compose up -d`
4. Если backend не запускается через Compose, его можно запустить локально:
   - `uvicorn backend.main:app --reload`
5. Для ручного запуска Celery:
   - `celery -A worker.celery_app worker --loglevel=INFO`
   - `celery -A worker.celery_app beat --loglevel=INFO`
6. Для старого RabbitMQ consumer-лога можно запустить:
   - `python -m worker.main`
7. Запустить Telegram-бота еще в одном терминале:
   - `python -m bot.main`

Если backend падает с `connection refused` на `127.0.0.1:5432`, значит PostgreSQL не запущен. Запусти `docker-compose up -d postgres` и затем снова стартуй backend.

Локальные панели:
- Backend API: `http://localhost:8000`
- Backend metrics: `http://localhost:8000/metrics`
- RabbitMQ Management: `http://localhost:15672` (`dating` / `dating`)
- MinIO Console: `http://localhost:9001` (`dating` / `dating-secret`)
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (`dating` / `dating`)

## Основные API
- `POST /api/v1/users/register` — регистрация/обновление Telegram-пользователя
- `GET /api/v1/users/{telegram_id}` — получение пользователя
- `PUT /api/v1/profiles/{telegram_id}` — создать или обновить анкету
- `GET /api/v1/profiles/{telegram_id}` — получить анкету
- `GET /api/v1/profiles` — список анкет
- `DELETE /api/v1/profiles/{telegram_id}` — очистить анкету
- `POST /api/v1/profiles/{telegram_id}/photos` — загрузить фото анкеты
- `GET /api/v1/profiles/{telegram_id}/photos` — список фото анкеты
- `GET /api/v1/photos/{photo_id}` — скачать фото
- `DELETE /api/v1/profiles/{telegram_id}/photos/{photo_id}` — удалить фото
- `GET /api/v1/feed/{telegram_id}/next` — следующая анкета по фильтрам и рейтингу
- `POST /api/v1/interactions` — лайк или пропуск
- `GET /api/v1/users/{telegram_id}/rating` — текущий рейтинг
- `GET /metrics` — Prometheus-метрики

## Очередь событий
- RabbitMQ доступен на `localhost:5672`.
- Веб-интерфейс RabbitMQ Management: `http://localhost:15672`.
- Логин и пароль по умолчанию: `dating` / `dating`.
- Backend публикует события в очередь `dating.events`.
- Worker читает очередь командой `python -m worker.main`.

## Фоновые задачи
- Celery использует RabbitMQ как broker и Redis как result backend.
- Backend ставит задачи `dating.refresh_user_rating` и `dating.process_interaction_event`.
- Celery Beat регулярно запускает `dating.refresh_all_ratings`.
- Если Celery выключен или недоступен, backend выполняет пересчет рейтинга синхронно.

## Тесты
- `source .venv/bin/activate`
- `pytest -q`

Тесты используют in-memory хранилище, кэш, S3 и fake MQ, поэтому не требуют запущенных Postgres, Redis, RabbitMQ и MinIO.
