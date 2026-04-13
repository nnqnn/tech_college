from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


MONEY_SCALE = Decimal("0.01")


def as_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "Customers"

    customer_id: Mapped[int] = mapped_column("CustomerID", Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column("FirstName", String(100), nullable=False)
    last_name: Mapped[str] = mapped_column("LastName", String(100), nullable=False)
    email: Mapped[str] = mapped_column("Email", String(255), nullable=False, unique=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "Products"

    product_id: Mapped[int] = mapped_column("ProductID", Integer, primary_key=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column("ProductName", String(200), nullable=False)
    price: Mapped[Decimal] = mapped_column("Price", Numeric(10, 2), nullable=False)

    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")


class Order(Base):
    __tablename__ = "Orders"

    order_id: Mapped[int] = mapped_column("OrderID", Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column("CustomerID", ForeignKey("Customers.CustomerID"), nullable=False)
    order_date: Mapped[datetime] = mapped_column("OrderDate", DateTime(timezone=True), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column("TotalAmount", Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "OrderItems"

    order_item_id: Mapped[int] = mapped_column("OrderItemID", Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column("OrderID", ForeignKey("Orders.OrderID"), nullable=False)
    product_id: Mapped[int] = mapped_column("ProductID", ForeignKey("Products.ProductID"), nullable=False)
    quantity: Mapped[int] = mapped_column("Quantity", Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column("Subtotal", Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="order_items")


@dataclass(frozen=True)
class OrderLine:
    product_id: int
    quantity: int


def get_engine():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://store_user:store_password@localhost:5432/store",
    )
    return create_engine(database_url, future=True)


def wait_for_db(engine, retries: int = 15, delay: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("База данных готова к работе.")
            return
        except OperationalError:
            print(f"База данных пока недоступна (попытка {attempt}/{retries})...")
            time.sleep(delay)
    raise RuntimeError("Cannot connect to database after several retries.")


def seed_data(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        with session.begin():
            customers_count = session.scalar(select(func.count(Customer.customer_id)))
            if not customers_count:
                session.add_all(
                    [
                        Customer(first_name="Ivan", last_name="Petrov", email="ivan.petrov@example.com"),
                        Customer(first_name="Anna", last_name="Smirnova", email="anna.smirnova@example.com"),
                    ]
                )

            products_count = session.scalar(select(func.count(Product.product_id)))
            if not products_count:
                session.add_all(
                    [
                        Product(product_name="Keyboard", price=Decimal("39.90")),
                        Product(product_name="Monitor", price=Decimal("189.50")),
                        Product(product_name="USB-C Cable", price=Decimal("12.00")),
                    ]
                )


def place_order_transaction(
    session_factory: sessionmaker,
    customer_id: int,
    lines: list[OrderLine],
) -> tuple[int, Decimal]:
    with session_factory() as session:
        with session.begin():
            customer = session.get(Customer, customer_id)
            if customer is None:
                raise ValueError(f"Customer with id={customer_id} does not exist")

            if not lines:
                raise ValueError("Order must include at least one item")

            order = Order(
                customer_id=customer_id,
                order_date=datetime.now(timezone.utc),
                total_amount=Decimal("0.00"),
            )
            session.add(order)
            session.flush()

            for line in lines:
                if line.quantity <= 0:
                    raise ValueError("Quantity must be greater than zero")

                product = session.get(Product, line.product_id)
                if product is None:
                    raise ValueError(f"Product with id={line.product_id} does not exist")

                subtotal = as_money(product.price * line.quantity)
                session.add(
                    OrderItem(
                        order_id=order.order_id,
                        product_id=line.product_id,
                        quantity=line.quantity,
                        subtotal=subtotal,
                    )
                )

            session.flush()

            items_total = session.scalar(
                select(func.coalesce(func.sum(OrderItem.subtotal), 0)).where(OrderItem.order_id == order.order_id)
            )
            order.total_amount = as_money(Decimal(items_total))
            return order.order_id, order.total_amount


def update_customer_email_transaction(session_factory: sessionmaker, customer_id: int, new_email: str) -> None:
    with session_factory() as session:
        with session.begin():
            customer = session.get(Customer, customer_id)
            if customer is None:
                raise ValueError(f"Customer with id={customer_id} does not exist")
            customer.email = new_email


def add_product_transaction(session_factory: sessionmaker, product_name: str, price: Decimal) -> int:
    if price <= 0:
        raise ValueError("Product price must be positive")

    with session_factory() as session:
        with session.begin():
            product = Product(product_name=product_name, price=as_money(price))
            session.add(product)
            session.flush()
            return product.product_id


def print_snapshot(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        customers = session.scalars(select(Customer).order_by(Customer.customer_id)).all()
        products = session.scalars(select(Product).order_by(Product.product_id)).all()
        orders = session.scalars(select(Order).order_by(Order.order_id)).all()
        order_items = session.scalars(select(OrderItem).order_by(OrderItem.order_item_id)).all()

    print("\nКлиенты:")
    for customer in customers:
        print(f"- #{customer.customer_id}: {customer.first_name} {customer.last_name}, {customer.email}")

    print("\nТовары:")
    for product in products:
        print(f"- #{product.product_id}: {product.product_name}, цена={product.price}")

    print("\nЗаказы:")
    for order in orders:
        print(
            f"- #{order.order_id}: клиент={order.customer_id}, "
            f"дата={order.order_date.isoformat()}, сумма={order.total_amount}"
        )

    print("\nПозиции заказов:")
    for item in order_items:
        print(
            f"- #{item.order_item_id}: заказ={item.order_id}, товар={item.product_id}, "
            f"количество={item.quantity}, подытог={item.subtotal}"
        )


def main() -> None:
    engine = get_engine()
    wait_for_db(engine)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    seed_data(session_factory)

    with session_factory() as session:
        customer_id = session.scalar(select(Customer.customer_id).order_by(Customer.customer_id))
        product_ids = session.scalars(select(Product.product_id).order_by(Product.product_id).limit(2)).all()

    if customer_id is None or len(product_ids) < 2:
        raise RuntimeError("Initial data is missing.")

    print("\nСценарий 1: транзакция оформления заказа")
    order_id, total = place_order_transaction(
        session_factory=session_factory,
        customer_id=customer_id,
        lines=[OrderLine(product_id=product_ids[0], quantity=1), OrderLine(product_id=product_ids[1], quantity=2)],
    )
    print(f"Заказ #{order_id} успешно создан, итоговая сумма: {total}")

    print("\nСценарий 2: транзакция обновления email клиента")
    new_email = f"customer{customer_id}.updated@example.com"
    update_customer_email_transaction(session_factory, customer_id=customer_id, new_email=new_email)
    print(f"Email клиента #{customer_id} успешно обновлен: {new_email}")

    print("\nСценарий 3: транзакция добавления нового товара")
    new_product_id = add_product_transaction(
        session_factory=session_factory,
        product_name="Wireless Mouse",
        price=Decimal("24.99"),
    )
    print(f"Товар #{new_product_id} успешно добавлен")

    print("\nИтоговое состояние базы данных:")
    print_snapshot(session_factory)


if __name__ == "__main__":
    main()
