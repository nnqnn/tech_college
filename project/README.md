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
  - перезаполнение и удаление анкеты
  - просмотр анкет
  - лайк/пропуск и сообщение о взаимном лайке
- Backend API:
  - регистрация пользователей
  - CRUD анкет
  - события лайк/пропуск
  - публикация событий `InteractionCreated` и `FeedRequested` в RabbitMQ
  - рейтинг в отдельной таблице `user_ratings`
  - выдача следующей анкеты с Redis-кэшем `candidates:{telegram_id}`
- Инфраструктура:
  - PostgreSQL для пользователей, анкет, взаимодействий и рейтингов
  - Redis для кэша пачек кандидатов
  - RabbitMQ для очереди событий
  - `docker-compose.yml` для локального запуска БД, Redis и RabbitMQ

## Быстрый старт
1. Установить зависимости:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Создать `.env` на основе `.env.example`.
3. Запустить инфраструктуру:
   - `docker compose up -d`
   - если установлен старый Compose: `docker-compose up -d`
   - если Redis уже запущен на `6379`, можно поднять только Postgres: `docker-compose up -d postgres`
4. Запустить backend:
   - `uvicorn backend.main:app --reload`
5. Запустить worker очереди в отдельном терминале:
   - `python -m worker.main`
6. Запустить Telegram-бота еще в одном терминале:
   - `python -m bot.main`

Если backend падает с `connection refused` на `127.0.0.1:5432`, значит PostgreSQL не запущен. Запусти `docker-compose up -d postgres` и затем снова стартуй backend.

## Основные API
- `POST /api/v1/users/register` — регистрация/обновление Telegram-пользователя
- `GET /api/v1/users/{telegram_id}` — получение пользователя
- `PUT /api/v1/profiles/{telegram_id}` — создать или обновить анкету
- `GET /api/v1/profiles/{telegram_id}` — получить анкету
- `GET /api/v1/profiles` — список анкет
- `DELETE /api/v1/profiles/{telegram_id}` — очистить анкету
- `GET /api/v1/feed/{telegram_id}/next` — следующая анкета по фильтрам и рейтингу
- `POST /api/v1/interactions` — лайк или пропуск
- `GET /api/v1/users/{telegram_id}/rating` — текущий рейтинг

## Очередь событий
- RabbitMQ доступен на `localhost:5672`.
- Веб-интерфейс RabbitMQ Management: `http://localhost:15672`.
- Логин и пароль по умолчанию: `dating` / `dating`.
- Backend публикует события в очередь `dating.events`.
- Worker читает очередь командой `python -m worker.main`.

## Тесты
- `source .venv/bin/activate`
- `pytest -q`

Тесты используют in-memory хранилище, кэш и fake MQ, поэтому не требуют запущенных Postgres, Redis и RabbitMQ.
