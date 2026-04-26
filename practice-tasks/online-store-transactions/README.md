# Online Store Transactions

Минимальная реализация SQL-транзакций для интернет-магазина на `Python + sqlite3`.

## Что есть

- `app.py` - инициализация БД и 3 транзакции:
  - размещение заказа
  - обновление email клиента
  - добавление товара
- `init.sql` - схема БД
- `Dockerfile`, `docker-compose.yml` - запуск в контейнере

## Запуск локально

```bash
python3 app.py
```

## Запуск в Docker

```bash
docker compose up --build
```
