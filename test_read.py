import sqlite3

conn = sqlite3.connect("event_booking.db")
cur = conn.cursor()

cur.execute("SELECT id, title, date, venue, seats FROM events")
rows = cur.fetchall()

for r in rows:
    print(r)

conn.close()
