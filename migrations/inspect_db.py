import sqlite3

conn = sqlite3.connect("gym.db")
cursor = conn.cursor()

print("\n=== TABLES ===")
tables = cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""").fetchall()

for table in tables:
    print(table[0])

print("\n=== ROW COUNTS ===")

for table in ["gyms", "members", "payments"]:
    try:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count}")
    except sqlite3.OperationalError:
        print(f"{table}: TABLE DOES NOT EXIST")

print("\n=== ALEMBIC VERSION ===")

try:
    version = cursor.execute("SELECT version_num FROM alembic_version").fetchall()

    if version:
        for row in version:
            print(row[0])
    else:
        print("No Alembic version recorded.")

except sqlite3.OperationalError:
    print("alembic_version table does not exist.")

conn.close()
