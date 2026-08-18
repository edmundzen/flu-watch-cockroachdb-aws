import os
import psycopg2

conn_str = os.environ.get("COCKROACH_CONN")

if not conn_str:
    print("Error: $env:COCKROACH_CONN is not set in this terminal session!")
else:
    try:
        conn = psycopg2.connect(conn_str)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        db_version = cur.fetchone()
        print("Connected successfully!")
        print("CockroachDB Version:", db_version[0])
        cur.close()
        conn.close()
    except Exception as e:
        print("Connection failed:", e)