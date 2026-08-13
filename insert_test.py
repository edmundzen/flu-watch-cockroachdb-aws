import psycopg2
import os

conn = psycopg2.connect(os.environ["COCKROACH_CONN"])
cur = conn.cursor()

cur.execute("""
    INSERT INTO season_baseline (region, season_year, epi_week, case_count, rain_mm, source)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (region, season_year, epi_week) DO NOTHING
""", ("Singapore", 2025, 42, 134, 12.4, "WHO FluNet"))

conn.commit()
print("Row inserted.")
cur.close()
conn.close()