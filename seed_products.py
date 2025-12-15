import sqlite3

conn = sqlite3.connect("event_booking.db")
cur = conn.cursor()

# optional: clear existing products so you don't duplicate
cur.execute("DELETE FROM products")
cur.execute("DELETE FROM sqlite_sequence WHERE name='products'")

cur.executemany("""
INSERT INTO products (name, description, price, stock)
VALUES (?, ?, ?, ?)
""", [
    ("Wireless Mouse", "2.4G ergonomic mouse", 12.99, 25),
    ("USB-C Cable", "1 meter fast charging cable", 4.99, 100),
    ("Laptop Stand", "Adjustable aluminum stand", 19.99, 15)
])

conn.commit()
conn.close()
print("Products seeded!")
