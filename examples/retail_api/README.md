# Retail API example

This is a standalone Python database application for exercising scirpy. It is a small stationery shop API built with FastAPI and SQLite.

The example intentionally uses a code + SQL design:

- `app.py` contains HTTP handlers, validation, transaction control, and business rules.
- `sql/schema.sql` defines the relational schema.
- `sql/queries.sql` contains the list and reporting queries.
- `sql/seed.sql` provides deterministic fixture data.

## Run

From the repository root, install the project and development dependencies:

```shell
uv sync
```

Start the API from the repository root:

```shell
uv run uvicorn examples.retail_api.app:app --reload
```

The seeded service is available at `http://127.0.0.1:8000/docs`. Set `SCIRPY_RETAIL_DB` to a SQLite file path to persist data instead of using the default in-memory database.

## Command-line usage

With the server running in another terminal:

```shell
# List all products.
curl http://127.0.0.1:8000/products

# List products that are currently in stock.
curl 'http://127.0.0.1:8000/products?in_stock_only=true'

# Create an order for two notebooks and one mechanical pencil.
curl -X POST http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"product_id":1,"quantity":2},{"product_id":2,"quantity":1}]}'

# View the order created above.
curl http://127.0.0.1:8000/orders/1

# Show units sold and revenue by product.
curl http://127.0.0.1:8000/reports/product-sales
```

## Check correctness

From the repository root, run:

```shell
uv run pytest examples/retail_api/tests
```

The tests check deterministic product reads, stock filtering, order totals, atomic stock updates, and aggregate sales revenue. Prices are stored as integer cents to avoid floating-point errors.
