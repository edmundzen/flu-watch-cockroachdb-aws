import psycopg2
import requests
import os

conn = psycopg2.connect(os.environ["COCKROACH_CONN"])
cur = conn.cursor()

url = "https://xmart-api-public.who.int/FLUMART/VIW_FNT"
params = {
    "$filter": "COUNTRY_CODE eq 'SGP' and ISO_YEAR ge 2019",
    "$format": "json"
}
r = requests.get(url, params=params)
rows = r.json()["value"]

count = 0
for row in rows:
    case_count = row.get("INF_ALL")
    if case_count is None:
        continue
    try:
        cur.execute("""
            INSERT INTO season_baseline (region, season_year, epi_week, case_count, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (region, season_year, epi_week) DO NOTHING
        """, (
            "Singapore",
            int(row["ISO_YEAR"]),
            int(row["ISO_WEEK"]),
            int(case_count),
            "WHO FluNet"
        ))
        count += 1
    except (ValueError, TypeError, KeyError):
        continue

conn.commit()
print(f"Inserted/checked {count} rows.")
cur.close()
conn.close()
