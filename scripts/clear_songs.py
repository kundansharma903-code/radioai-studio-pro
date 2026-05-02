import sqlite3
import os

# DB path
db_path = os.path.join(
    os.environ.get('LOCALAPPDATA', ''),
    'RadioAI', 'radioai.db'
)

print(f"DB Path: {db_path}")

conn = sqlite3.connect(db_path)

# Count before
songs_count = conn.execute(
    "SELECT COUNT(*) FROM songs"
).fetchone()[0]

print(f"Songs before: {songs_count}")

# Delete ONLY songs table data
conn.execute("DELETE FROM songs")
conn.commit()

# Reset auto-increment counter
conn.execute(
    "DELETE FROM sqlite_sequence WHERE name='songs'"
)
conn.commit()

# Verify
songs_after = conn.execute(
    "SELECT COUNT(*) FROM songs"
).fetchone()[0]

print(f"Songs after: {songs_after}")
print("Done - only songs deleted")
print("All other data untouched:")

# Show other tables are safe
tables = ['campaigns', 'jingles',
          'sweepers', 'categories',
          'users', 'settings']
for t in tables:
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {t}"
        ).fetchone()[0]
        print(f"  {t}: {count} records (safe)")
    except:
        pass

conn.close()
