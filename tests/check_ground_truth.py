import sqlite3


GROUND_TRUTH_SQL = {
    "customer_count": "SELECT COUNT(*) FROM customers",
    "product_count": "SELECT COUNT(*) FROM products",
    "order_count": "SELECT COUNT(*) FROM orders",
    "customers_never_ordered": """
        SELECT c.name FROM customers c
        LEFT JOIN orders o ON c.customer_id = o.customer_id
        WHERE o.order_id IS NULL
    """,
    "products_never_ordered": """
        SELECT p.name FROM products p
        LEFT JOIN order_items oi ON p.product_id = oi.product_id
        WHERE oi.order_item_id IS NULL
    """,
    "best_selling_category": """
        WITH category_revenue AS (
            SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY p.category
        ), ranked AS (
            SELECT category, RANK() OVER (ORDER BY revenue DESC) AS rank
            FROM category_revenue
        )
        SELECT category FROM ranked WHERE rank = 1
    """,
    "cancelled_order_percentage": """
        SELECT ROUND(100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2)
        FROM orders
    """,
    "top_ordering_customers": """
        WITH order_counts AS (
            SELECT customer_id, COUNT(*) AS order_count
            FROM orders
            GROUP BY customer_id
        ), ranked AS (
            SELECT customer_id, RANK() OVER (ORDER BY order_count DESC) AS rank
            FROM order_counts
        )
        SELECT c.name
        FROM ranked r
        JOIN customers c ON c.customer_id = r.customer_id
        WHERE r.rank = 1
    """,
    "customers_above_average_spend": """
        WITH spend AS (
            SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            GROUP BY o.customer_id
        )
        SELECT COUNT(*) FROM spend WHERE total > (SELECT AVG(total) FROM spend)
    """,
    "customers_with_more_than_three_categories": """
        SELECT COUNT(*) FROM (
            SELECT c.customer_id
            FROM customers c
            JOIN orders o ON c.customer_id = o.customer_id
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY c.customer_id
            HAVING COUNT(DISTINCT p.category) > 3
        )
    """,
    "top_ten_customer_revenue_percentage": """
        WITH spend AS (
            SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            GROUP BY o.customer_id
        ), ranked AS (
            SELECT total, RANK() OVER (ORDER BY total DESC) AS rank FROM spend
        )
        SELECT ROUND(100.0 * (SELECT SUM(total) FROM ranked WHERE rank <= 10) /
                     (SELECT SUM(total) FROM spend), 2)
    """,
    "months_with_orders": "SELECT COUNT(DISTINCT strftime('%Y-%m', order_date)) FROM orders",
    "customers_never_ordered_electronics": """
        SELECT c.name FROM customers c
        WHERE c.customer_id NOT IN (
            SELECT o.customer_id
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE p.category = 'Electronics'
        )
    """,
}


def get_ground_truth(db_path="data/ecommerce.db"):
    conn = sqlite3.connect(db_path)
    try:
        return {
            name: conn.execute(sql).fetchall()
            for name, sql in GROUND_TRUTH_SQL.items()
        }
    finally:
        conn.close()


if __name__ == "__main__":
    for name, rows in get_ground_truth().items():
        print(f"--- {name} ---")
        print(rows)
