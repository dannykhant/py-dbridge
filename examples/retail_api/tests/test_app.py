from fastapi.testclient import TestClient

from examples.retail_api.app import create_app


def client() -> TestClient:
    return TestClient(create_app(seed=True))


def test_seeded_products_and_stock_filter() -> None:
    with client() as api:
        assert api.get("/products").json() == [
            {"id": 1, "name": "Notebook", "price_cents": 1299, "stock": 10},
            {"id": 2, "name": "Mechanical Pencil", "price_cents": 799, "stock": 5},
            {"id": 3, "name": "Desk Lamp", "price_cents": 2499, "stock": 0},
        ]
        assert [p["id"] for p in api.get("/products?in_stock_only=true").json()] == [1, 2]


def test_create_order_calculates_total_and_decrements_stock() -> None:
    with client() as api:
        response = api.post("/orders", json={"items": [
            {"product_id": 1, "quantity": 2},
            {"product_id": 2, "quantity": 1},
        ]})
        assert response.status_code == 201
        assert response.json()["total_cents"] == 3397
        assert response.json()["items"] == [
            {"product_id": 1, "quantity": 2, "unit_price_cents": 1299},
            {"product_id": 2, "quantity": 1, "unit_price_cents": 799},
        ]
        products = {p["id"]: p for p in api.get("/products").json()}
        assert products[1]["stock"] == 8
        assert products[2]["stock"] == 4


def test_order_is_atomic_when_stock_is_insufficient() -> None:
    with client() as api:
        response = api.post("/orders", json={"items": [
            {"product_id": 1, "quantity": 1},
            {"product_id": 2, "quantity": 99},
        ]})
        assert response.status_code == 409
        assert api.get("/products").json()[0]["stock"] == 10
        assert api.get("/orders/1").status_code == 404


def test_sales_report_uses_recorded_unit_prices() -> None:
    with client() as api:
        api.post("/orders", json={"items": [{"product_id": 1, "quantity": 2}]})
        assert api.get("/reports/product-sales").json() == [
            {"product_id": 1, "name": "Notebook", "units_sold": 2, "revenue_cents": 2598},
            {"product_id": 2, "name": "Mechanical Pencil", "units_sold": 0, "revenue_cents": 0},
            {"product_id": 3, "name": "Desk Lamp", "units_sold": 0, "revenue_cents": 0},
        ]
