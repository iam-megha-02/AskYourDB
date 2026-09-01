import sqlite3
import random
from faker import Faker

fake = Faker()
conn = sqlite3.connect("ecommerce.db")
cursor = conn.cursor()

# --- Customers ---
customers = []
for i in range(1, 51):  # 50 customers
    customers.append((
        i,
        fake.name(),
        fake.email(),
        fake.city(),
        fake.date_between(start_date="-2y", end_date="today").isoformat()
    ))
cursor.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers)

# --- Products ---
categories = ["Electronics", "Clothing", "Home & Kitchen", "Books", "Sports"]
products = []
for i in range(1, 31):  # 30 products
    products.append((
        i,
        fake.word().capitalize() + " " + random.choice(["Pro", "Max", "Basic", "Plus"]),
        random.choice(categories),
        round(random.uniform(5, 500), 2)
    ))
cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

# --- Orders ---
statuses = ["completed", "pending", "cancelled"]
orders = []
for order_id in range(1, 151):  # 150 orders
    orders.append((
        order_id,
        random.randint(1, 50),
        fake.date_between(start_date="-1y", end_date="today").isoformat(),
        random.choice(statuses)
    ))
cursor.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)

# --- Order items ---
order_items = []
item_id = 1
for oid in range(1, 151):
    for _ in range(random.randint(1, 4)):  # 1-4 items per order
        pid = random.randint(1, 30)
        qty = random.randint(1, 5)
        cursor.execute("SELECT price FROM products WHERE product_id = ?", (pid,))
        price = cursor.fetchone()[0]
        order_items.append((item_id, oid, pid, qty, price))
        item_id += 1
cursor.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", order_items)

conn.commit()
conn.close()
print("Sample data inserted successfully.")