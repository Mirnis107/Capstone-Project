import sqlite3

conn = sqlite3.connect("event_booking.db")
cur = conn.cursor()

# insert only if same title+date+venue doesn't already exist
cur.execute("""
INSERT INTO events (title, date, venue, seats)
SELECT ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM events WHERE title = ? AND date = ? AND venue = ?
)
""", ("Tech Talk 2025", "2025-12-20", "Main Hall", 50,
      "Tech Talk 2025", "2025-12-20", "Main Hall"))

conn.commit()
conn.close()

print("Seed complete (no duplicates).")

