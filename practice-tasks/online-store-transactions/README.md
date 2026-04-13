# Online Store Transactions

Решение практического задания с тремя транзакционными сценариями для схемы:

- `Customers (CustomerID, FirstName, LastName, Email)`
- `Products (ProductID, ProductName, Price)`
- `Orders (OrderID, CustomerID, OrderDate, TotalAmount)`
- `OrderItems (OrderItemID, OrderID, ProductID, Quantity, Subtotal)`

## Что реализовано

- **Сценарий 1:** транзакция размещения заказа:
  - создается запись в `Orders`;
  - добавляются позиции в `OrderItems`;
  - пересчитывается и обновляется `Orders.TotalAmount` как сумма `Subtotal`.
- **Сценарий 2:** атомарное обновление email клиента в `Customers`.
- **Сценарий 3:** атомарное добавление нового продукта в `Products`.

Реализация выполнена на Python с ORM SQLAlchemy и PostgreSQL.

## Запуск

Из директории `online-store-transactions`:

```bash
docker compose up --build
```

После запуска контейнер `app`:

1. создаст таблицы;
2. добавит начальные данные (если таблицы пустые);
3. выполнит 3 сценария транзакций;
4. выведет итоговое состояние таблиц в лог.
