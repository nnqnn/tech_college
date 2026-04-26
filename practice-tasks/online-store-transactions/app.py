import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "data", "store.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "init.sql")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(SCHEMA_PATH, encoding="utf-8") as file:
            conn.executescript(file.read())
        conn.commit()
    finally:
        conn.close()


def seed_data():
    with get_connection() as conn:
        cursor = conn.cursor()
        if not cursor.execute("SELECT COUNT(*) FROM Customers").fetchone()[0]:
            cursor.executemany(
                "INSERT INTO Customers (FirstName, LastName, Email) VALUES (?, ?, ?)",
                [
                    ("Ivan", "Ivanov", "ivan@example.com"),
                    ("Maria", "Petrova", "maria@example.com"),
                ],
            )
        if not cursor.execute("SELECT COUNT(*) FROM Products").fetchone()[0]:
            cursor.executemany(
                "INSERT INTO Products (ProductName, Price) VALUES (?, ?)",
                [("Laptop", 50000), ("Mouse", 1500), ("Keyboard", 3000)],
            )


def place_order(customer_id, items):
    with get_connection() as conn:
        cursor = conn.cursor()
        if not cursor.execute(
            "SELECT 1 FROM Customers WHERE CustomerID = ?", (customer_id,)
        ).fetchone():
            raise ValueError(f"Customer with ID {customer_id} not found")
        cursor.execute(
            "INSERT INTO Orders (CustomerID, OrderDate, TotalAmount) VALUES (?, ?, 0)",
            (customer_id, datetime.now().isoformat(timespec="seconds")),
        )
        order_id = cursor.lastrowid
        total = 0
        for item in items:
            product_id, quantity = item["product_id"], item["quantity"]
            row = cursor.execute(
                "SELECT Price FROM Products WHERE ProductID = ?", (product_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Product with ID {product_id} not found")
            subtotal = row[0] * quantity
            total += subtotal
            cursor.execute(
                "INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal) VALUES (?, ?, ?, ?)",
                (order_id, product_id, quantity, subtotal),
            )
        cursor.execute(
            "UPDATE Orders SET TotalAmount = ? WHERE OrderID = ?", (total, order_id)
        )
        return order_id, total


def update_customer_email(customer_id, new_email):
    with get_connection() as conn:
        cursor = conn.cursor()
        if not cursor.execute(
            "SELECT 1 FROM Customers WHERE CustomerID = ?", (customer_id,)
        ).fetchone():
            raise ValueError(f"Customer with ID {customer_id} not found")
        cursor.execute(
            "UPDATE Customers SET Email = ? WHERE CustomerID = ?",
            (new_email, customer_id),
        )


def add_product(product_name, price):
    if price < 0:
        raise ValueError("Price cannot be negative")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Products (ProductName, Price) VALUES (?, ?)",
            (product_name, price),
        )
        return cursor.lastrowid


def fetch_one(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def main():
    init_db()
    seed_data()
    order_id, total = place_order(
        1,
        [
            {"product_id": 1, "quantity": 1},
            {"product_id": 2, "quantity": 2},
            {"product_id": 3, "quantity": 1},
        ],
    )
    print(f"Order #{order_id} created, total: {total}")
    update_customer_email(1, "ivan_new@example.com")
    print(f"Updated email: {fetch_one('SELECT Email FROM Customers WHERE CustomerID = 1')[0]}")
    product_id = add_product("Monitor", 25000)
    print(f"Product added with ID #{product_id}")


if __name__ == "__main__":
    main()
