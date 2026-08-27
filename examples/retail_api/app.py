from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


SQL_DIR = Path(__file__).with_name("sql")


class OrderItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderRequest(BaseModel):
    items: list[OrderItemRequest] = Field(min_length=1)


def load_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


class Store:
    def __init__(self, database: str, seed: bool = False) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(load_sql("schema.sql"))
        if seed:
            self.connection.executescript(load_sql("seed.sql"))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def create_app(database: str = ":memory:", seed: bool = False) -> FastAPI:
    store = Store(database, seed=seed)
    app = FastAPI(title="Scirpy Retail API", version="1.0.0")
    app.state.store = store

    @app.on_event("shutdown")
    def close_database() -> None:
        store.close()

    @app.get("/products")
    def list_products(in_stock_only: bool = False) -> list[dict]:
        query = load_sql("queries.sql")
        statement = query.split("-- LIST_PRODUCTS")[1].split("--")[0]
        rows = store.connection.execute(statement, (int(in_stock_only),)).fetchall()
        return [dict(row) for row in rows]

    @app.post("/orders", status_code=201)
    def create_order(order: OrderRequest) -> dict:
        # Merge duplicate product lines before checking and decrementing stock.
        quantities: dict[int, int] = {}
        for item in order.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity

        connection = store.connection
        try:
            with connection:
                products = {}
                for product_id, quantity in quantities.items():
                    row = connection.execute(
                        "SELECT id, name, price_cents, stock FROM products WHERE id = ?",
                        (product_id,),
                    ).fetchone()
                    if row is None:
                        raise HTTPException(404, f"product {product_id} does not exist")
                    if row["stock"] < quantity:
                        raise HTTPException(409, f"not enough stock for product {product_id}")
                    products[product_id] = (row, quantity)

                total_cents = sum(row["price_cents"] * quantity for row, quantity in products.values())
                cursor = connection.execute(
                    "INSERT INTO orders (total_cents) VALUES (?)", (total_cents,)
                )
                order_id = cursor.lastrowid
                for product_id, (row, quantity) in products.items():
                    connection.execute(
                        "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) "
                        "VALUES (?, ?, ?, ?)",
                        (order_id, product_id, quantity, row["price_cents"]),
                    )
                    connection.execute(
                        "UPDATE products SET stock = stock - ? WHERE id = ?",
                        (quantity, product_id),
                    )
        except HTTPException:
            raise

        return get_order(order_id)

    @app.get("/orders/{order_id}")
    def get_order(order_id: int) -> dict:
        order = store.connection.execute(
            "SELECT id, total_cents, created_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise HTTPException(404, "order does not exist")
        items = store.connection.execute(
            "SELECT product_id, quantity, unit_price_cents FROM order_items "
            "WHERE order_id = ? ORDER BY product_id",
            (order_id,),
        ).fetchall()
        return {**dict(order), "items": [dict(item) for item in items]}

    @app.get("/reports/product-sales")
    def product_sales() -> list[dict]:
        query = load_sql("queries.sql")
        statement = query.split("-- PRODUCT_SALES")[1].split("--")[0]
        rows = store.connection.execute(statement).fetchall()
        return [dict(row) for row in rows]

    return app


app = create_app(os.environ.get("SCIRPY_RETAIL_DB", ":memory:"), seed=True)
