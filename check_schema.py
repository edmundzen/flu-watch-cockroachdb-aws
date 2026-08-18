import os
import psycopg2

conn = psycopg2.connect(os.environ["COCKROACH_CONN"])
cur = conn.cursor()

cur.execute("""
    SELECT table_schema, column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'anomaly_results'
    ORDER BY ordinal_position
""")
print("COLUMNS IN anomaly_results:")
for schema, name, dtype in cur.fetchall():
    print(f"  [{schema}] {name:25s} {dtype}")

cur.execute("SELECT * FROM anomaly_results LIMIT 5")
print("\nSAMPLE ROWS:")
for row in cur.fetchall():
    print(" ", row)