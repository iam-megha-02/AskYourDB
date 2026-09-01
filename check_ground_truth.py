import sqlite3

conn = sqlite3.connect("ecommerce.db")
cursor = conn.cursor()

print("--- Customers who never ordered ---")
cursor.execute("""
    SELECT c.name FROM customers c
    LEFT JOIN orders o ON c.customer_id = o.customer_id
    WHERE o.order_id IS NULL
""")
print(cursor.fetchall())

print("\n--- Products never ordered ---")
cursor.execute("""
    SELECT p.name FROM products p
    LEFT JOIN order_items oi ON p.product_id = oi.product_id
    WHERE oi.order_item_id IS NULL
""")
print(cursor.fetchall())

print("\n--- Average items per order ---")
cursor.execute("""
    SELECT AVG(item_count) FROM (
        SELECT order_id, COUNT(*) AS item_count
        FROM order_items GROUP BY order_id
    )
""")
print(cursor.fetchall())

print("\n--- Best-selling category by revenue ---")
cursor.execute("""
    SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
    FROM order_items oi
    JOIN products p ON oi.product_id = p.product_id
    GROUP BY p.category
    ORDER BY revenue DESC
""")
print(cursor.fetchall())

print("\n--- Percentage of orders cancelled ---")
cursor.execute("""
    SELECT
        ROUND(100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2)
    FROM orders
""")
print(cursor.fetchall())

print("\n--- Customers who spent more than the average customer ---")
cursor.execute("""
    WITH spend AS (
        SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total
        FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY o.customer_id
    )
    SELECT COUNT(*) FROM spend WHERE total > (SELECT AVG(total) FROM spend)
""")
print(cursor.fetchall())

print("\n--- Customers who ordered from more than 3 different categories ---")
cursor.execute("""
    SELECT c.name, COUNT(DISTINCT p.category) AS cat_count
    FROM customers c
    JOIN orders o ON c.customer_id = o.customer_id
    JOIN order_items oi ON o.order_id = oi.order_id
    JOIN products p ON oi.product_id = p.product_id
    GROUP BY c.customer_id
    HAVING cat_count > 3
""")
print(cursor.fetchall())

print("\n--- What percentage of revenue comes from the top 10 customers ---")
cursor.execute("""
    WITH spend AS (
        SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total
        FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY o.customer_id
    ), ranked AS (
        SELECT total, RANK() OVER (ORDER BY total DESC) AS rnk FROM spend
    )
    SELECT ROUND(100.0 * (SELECT SUM(total) FROM ranked WHERE rnk <= 10) /
                 (SELECT SUM(total) FROM spend), 2)
""")
print(cursor.fetchall())

print("\n--- Number of distinct months with at least one order ---")
cursor.execute("""
    SELECT COUNT(DISTINCT strftime('%Y-%m', order_date)) FROM orders
""")
print(cursor.fetchall())

print("\n--- Customers who never ordered from Electronics ---")
cursor.execute("""
    SELECT c.name FROM customers c
    WHERE c.customer_id NOT IN (
        SELECT o.customer_id FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE p.category = 'Electronics'
    )
""")
print(cursor.fetchall())

conn.close()