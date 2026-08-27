"""Example: Iterative product lookup — BEFORE optimization."""
import psycopg2

def get_products(conn, product_ids: list[int]) -> list[dict]:
    """Fetch products one at a time (N+1 query pattern)."""
    cursor = conn.cursor()
    results = []
    for product_id in product_ids:
        cursor.execute(
            "SELECT id, name, price_cents FROM products WHERE id = %s",
            (product_id,),
        )
        row = cursor.fetchone()
        if row:
            results.append({"id": row[0], "name": row[1], "price": row[2]})
    cursor.close()
    return results
