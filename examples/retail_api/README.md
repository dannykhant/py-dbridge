# Retail API example

This is a standalone Python database application for exercising scirpy. It is a small stationery shop API built with FastAPI and SQLite.

The example intentionally uses a code + SQL design:

- `app.py` contains HTTP handlers, validation, transaction control, and business rules.
- `sql/schema.sql` defines the relational schema.
- `sql/queries.sql` contains the list and reporting queries.
- `sql/seed.sql` provides deterministic fixture data.

## Transformation rules covered

`app.py` is also an input corpus for scirpy. Each handler below is written so the
transformation engine exercises one of the five DBridge rules (the engine
rewrites the whole module at once):

| Rule                 | Handler / code block                                            |
| -------------------- | -------------------------------------------------------------- |
| Loop Splitting       | `POST /orders` — per-product `SELECT` in a `for` loop          |
| Query Rewrite        | `GET /products/bulk` — single-row `SELECT` rewritten to `IN`   |
| Conditional Handling | `GET /products/availability` — `SELECT` guarded by an `if`     |
| Statement Reordering | `GET /reports/restock-cost` — PRE before / POST after execute  |
| While Loop Support   | `GET /reports/low-stock` — `SELECT` inside a `while` loop      |

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

# Look up several products in one call (Query Rewrite: id IN (...)).
curl 'http://127.0.0.1:8000/products/bulk?ids=1,2'

# Look up products, skipping non-positive ids (Conditional Handling).
curl 'http://127.0.0.1:8000/products/availability?ids=1,-1,2'

# Show restock cost per product (Statement Reordering).
curl 'http://127.0.0.1:8000/reports/restock-cost?threshold=5'

# Walk the product list by index to find low-stock items (While Loop Support).
curl http://127.0.0.1:8000/reports/low-stock
```

## Check correctness

From the repository root, run:

```shell
uv run pytest examples/retail_api/tests
```

The tests check deterministic product reads, stock filtering, order totals, atomic stock updates, and aggregate sales revenue. Prices are stored as integer cents to avoid floating-point errors.
