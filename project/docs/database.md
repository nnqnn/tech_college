# Схема данных (PostgreSQL)

Схема намеренно компактная: хранит анкету, фото, взаимодействия и итоговый рейтинг в отдельной таблице (под регулярные пересчёты воркером).

## ER-диаграмма

```mermaid
erDiagram
  users {
    bigint telegram_id PK
    int age
    varchar gender
    varchar interests
    varchar city
    int profile_completion_pct
    int photos_count
    int age_pref_min
    int age_pref_max
    varchar gender_pref
    varchar city_pref
    varchar interests_pref
    timestamp last_activity
    bigint referral_telegram_id FK
    timestamp created_at
    timestamp updated_at
  }

  user_photos {
    uuid id PK
    bigint telegram_id FK
    varchar s3_key
    varchar content_type
    bigint file_size
    int sort_order
    timestamp created_at
  }

  user_interactions {
    uuid id PK
    bigint requester_telegram_id FK
    bigint responder_telegram_id FK
    boolean is_like
    timestamp created_at
  }

  user_ratings {
    bigint telegram_id PK, FK
    double primary_score
    double behavioral_score
    double referral_score
    double total_score
    timestamp calculated_at
  }

  users ||--o{ user_photos : has
  users ||--o{ user_interactions : requester
  users ||--o{ user_interactions : responder
  users ||--o| user_ratings : rating
  users ||--o{ users : referral
```

## Ограничения и индексы (идея)
- **`users.telegram_id`** — основной идентификатор пользователя (удобно, т.к. приходит из Telegram).
- **Рефералка**: `users.referral_telegram_id -> users.telegram_id` (nullable).
- **Уникальность взаимодействия**: один пользователь не должен оценивать одну и ту же анкету больше одного раза:
  - Unique(`requester_telegram_id`, `responder_telegram_id`) в `user_interactions`.
- **Индексы**:
  - `user_interactions (requester_telegram_id, created_at)`
  - `user_interactions (responder_telegram_id, created_at)`
  - `user_photos (telegram_id, sort_order)`
  - `users (city, gender, age)`
  - `user_ratings (total_score)`

## Фото
- Сами изображения хранятся в MinIO/S3.
- `user_photos.s3_key` — ключ объекта вида `profiles/{telegram_id}/{photo_id}.jpg`.
- `content_type` и `file_size` нужны для корректной выдачи файла и базовой диагностики.
- `users.photos_count` синхронизируется при загрузке/удалении фото и влияет на первичный рейтинг.
- Backend поддерживает лимит фото анкеты через `MAX_PROFILE_PHOTOS`.

## События, которые пишет Backend
Backend фиксирует взаимодействие в `user_interactions`, а затем публикует событие в MQ. Пример payload (логическая модель):
- `InteractionCreated`: requester, responder, is_like, created_at
- `FeedRequested`: requester, timestamp, context (например, город/предпочтения)

После изменения анкеты, фото или взаимодействия Backend также ставит Celery-задачу на пересчет рейтинга. Celery Beat регулярно запускает полный пересчет таблицы `user_ratings`.

## Рейтинг: уровни и хранение

### Уровень 1 — первичный (`primary_score`)
Считается из анкеты:
- Возраст/пол/интересы/город
- **Полнота профиля** (`profile_completion_pct`)
- **Количество фото** (`photos_count`)
- Первичные предпочтения: возрастной диапазон, пол, город, интересы

### Уровень 2 — поведенческий (`behavioral_score`)
Считается из фактов взаимодействий:
- Количество лайков
- Соотношение лайков/пропусков
- Частота взаимных лайков (мэтчей) как доля взаимных лайков
- Частота инициирования диалогов после мэтча (как событие, если добавится)
- Временные параметры активности (например, активность по часам суток через `last_activity` + события)

### Уровень 3 — комбинированный (`total_score`)
Интегрирует уровни по весовой модели и учитывает реферальный фактор:
\[
total\_score = w_1 \cdot primary\_score + w_2 \cdot behavioral\_score + w_3 \cdot referral\_score
\]
где \(w_1 + w_2 + w_3 = 1\).

`referral_score` — надбавка за приглашённых пользователей (например, логика «за каждого активного приглашённого»).

## Кэш выдачи (Redis): формат ключей
- `candidates:{telegram_id}` → список следующих анкет (например, 10 `telegram_id`), TTL 5–15 минут.
- Когда список заканчивается, Backend снова формирует пачку на основе `user_ratings.total_score` + фильтров предпочтений.
