# Dating backend (базовый прототип)

Репозиторий содержит описание архитектуры и минимальную рабочую реализацию:
- Telegram-бот как внешний интерфейс
- Backend API на FastAPI
- Базовую регистрацию пользователя по `telegram_id` на `/start`

## Документация
- `docs/services.md` — сервисы и их ответственность
- `docs/architecture.md` — схема взаимодействия компонентов (Mermaid)
- `docs/database.md` — схема БД (Mermaid ERD) и ключевые правила хранения данных/рейтинга

## Что реализовано сейчас
- Базовый Telegram-бот (`bot/`):
  - обработка `/start` и `/help`
  - простое меню (кнопки-заглушки)
  - регистрация через Backend API
- Минимальный Backend API (`backend/`):
  - `POST /api/v1/users/register` — регистрация/апдейт пользователя
  - `GET /api/v1/users/{telegram_id}` — получение пользователя
  - `GET /health` — healthcheck
- Тесты базовой регистрации (`tests/test_registration.py`)

## Что пока не реализовано
- CRUD для анкет
- Алгоритм ранжирования
- Redis-кэш анкет
- MQ/Celery/S3 интеграции

## Быстрый старт
1. Установить зависимости:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Запустить backend:
   - `uvicorn backend.main:app --reload`
3. Запустить Telegram-бота (в другом терминале):
   - `export TELEGRAM_BOT_TOKEN="ваш_токен"`
   - `export BACKEND_API_URL="http://localhost:8000"`
   - `python -m bot.main`

## Примечание
Сейчас backend хранит пользователей в памяти процесса (in-memory) только для базового этапа интеграции интерфейса бота и регистрации.

