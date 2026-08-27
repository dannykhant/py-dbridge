-- LIST_PRODUCTS
SELECT id, name, price_cents, stock
FROM products
WHERE (? = 0 OR stock > 0)
ORDER BY id;

-- PRODUCT_SALES
SELECT p.id AS product_id,
       p.name,
       COALESCE(SUM(oi.quantity), 0) AS units_sold,
       COALESCE(SUM(oi.quantity * oi.unit_price_cents), 0) AS revenue_cents
FROM products AS p
LEFT JOIN order_items AS oi ON oi.product_id = p.id
GROUP BY p.id, p.name
ORDER BY p.id;
