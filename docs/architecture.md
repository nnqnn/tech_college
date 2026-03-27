# Архитектура

Система построена вокруг Backend API, который обслуживает Telegram-бота, сохраняет данные в PostgreSQL, кэширует выдачу в Redis и отправляет события взаимодействий в очередь для асинхронной обработки.

## Общая схема компонентов

```mermaid
flowchart LR
  U[User] -->|Telegram messages| TB[Telegram Bot]
  TB -->|HTTP request webhook| API[Backend API FastAPI]

  API --> PG[(PostgreSQL)]
  API --> RDS[(Redis)]
  API --> S3[(S3 / MinIO)]
  API --> MQ[(MQ: RabbitMQ / Kafka)]

  MQ --> W[Celery Worker]
  W --> PG
  W --> RDS

  API -->|metrics| PR[(Prometheus)]
  W -->|metrics| PR
  PR --> GF[Grafana]
```
