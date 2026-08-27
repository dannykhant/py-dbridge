"""Example: Batched product lookup — AFTER optimization by py-dbridge."""
import psycopg2

def get_products(conn, product_ids: list[int]) -> list[dict]:
    """Fetch products in a single batch query (set-oriented)."""
    cursor = conn.cursor()

    # Phase 1: Collect parameters (from loop splitting)
    _pyd_params = list(product_ids)

    # Phase 2: Batch query execution
    cursor.execute(
        "SELECT id, name, price_cents FROM products WHERE id = ANY(%s)",
        (_pyd_params,),
    )
    _pyd_result_map = {row[0]: row for row in cursor.fetchall()}

    # Phase 3: Process results in original order
    results = []
    for product_id in product_ids:
        row = _pyd_result_map.get(product_id)
        if row:
            results.append({"id": row[0], "name": row[1], "price": row[2]})

    cursor.close()
    return results
