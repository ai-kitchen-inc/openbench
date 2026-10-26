"""Create the sample SQLite database for Dashboard Chat.

Writes ``sample.db`` next to the example root: a small coffee-shop
dataset (products, stores, orders, order_items) spanning 12 months.
Idempotent — recreates the file on every run. Seeded RNG so everyone
gets the same data.

Usage:
    python scripts/create_sample_db.py
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "sample.db"

PRODUCTS = [
    ("Espresso", "coffee", 2.50),
    ("Americano", "coffee", 3.00),
    ("Latte", "coffee", 4.20),
    ("Cappuccino", "coffee", 4.00),
    ("Flat White", "coffee", 4.30),
    ("Cold Brew", "coffee", 4.50),
    ("Matcha Latte", "tea", 4.80),
    ("Earl Grey", "tea", 3.20),
    ("Croissant", "food", 3.50),
    ("Banana Bread", "food", 3.80),
    ("Blueberry Muffin", "food", 3.60),
    ("Ham & Cheese Toastie", "food", 6.50),
]

STORES = [
    ("Downtown", "Jakarta"),
    ("Riverside", "Jakarta"),
    ("Campus Corner", "Bandung"),
    ("Harbor Point", "Surabaya"),
]

CHANNELS = ("in-store", "takeaway", "delivery")


def main() -> None:
    rng = random.Random(42)
    DB_PATH.unlink(missing_ok=True)
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL
        );
        CREATE TABLE stores (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            store_id INTEGER NOT NULL REFERENCES stores(id),
            channel TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );
        """
    )
    cursor.executemany("INSERT INTO products (name, category, price) VALUES (?, ?, ?)", PRODUCTS)
    cursor.executemany("INSERT INTO stores (name, city) VALUES (?, ?)", STORES)

    start = datetime(2025, 7, 1, 7, 0, 0)
    order_id = 0
    for day in range(365):
        date = start + timedelta(days=day)
        # Weekends are busier; slight growth over the year.
        base = 8 if date.weekday() < 5 else 12
        n_orders = rng.randint(base, base + 6) + day // 90
        for _ in range(n_orders):
            order_id += 1
            timestamp = date + timedelta(hours=rng.randint(0, 12), minutes=rng.randint(0, 59))
            store_id = rng.randint(1, len(STORES))
            channel = rng.choices(CHANNELS, weights=(5, 3, 2))[0]
            cursor.execute(
                "INSERT INTO orders (id, store_id, channel, created_at) VALUES (?, ?, ?, ?)",
                (order_id, store_id, channel, timestamp.isoformat(sep=" ")),
            )
            for _ in range(rng.randint(1, 4)):
                product_index = rng.randint(0, len(PRODUCTS) - 1)
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        order_id,
                        product_index + 1,
                        rng.randint(1, 3),
                        PRODUCTS[product_index][2],
                    ),
                )
    connection.commit()
    counts = {
        table: cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("products", "stores", "orders", "order_items")
    }
    connection.close()
    print(f"Created {DB_PATH}")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")
    print("\nConnect with URL: sqlite:///sample.db")


if __name__ == "__main__":
    main()
