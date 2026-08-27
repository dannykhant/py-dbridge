"""Example: Iterative product lookup — BEFORE optimization."""
import psycopg2

def get_products(conn, product_ids: list[int]) -> list[dict]:
    """Fetch products one at a time (N+1 query pattern)."""
    cursor = conn.cursor()
    results = []
    _pyd_params = list(product_ids)
    cursor.execute('SELECT id, name, price_cents FROM products WHERE id = ANY(%s)', (_pyd_params,))
    _pyd_result_map = {row[0]: row for row in cursor.fetchall()}
    for product_id in product_ids:
        row = _pyd_result_map.get(product_id)
        if row:
            results.append({'id': row[0], 'name': row[1], 'price': row[2]})
    cursor.close()
    return results