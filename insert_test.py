import os, psycopg2
conn = psycopg2.connect(os.environ["COCKROACH_CONN"])
cur = conn.cursor()
cur.execute("""
    INSERT INTO anomaly_results
      (region, season_year, epi_week, current_cases, historical_avg_cases,
       historical_years, anomaly, anomaly_score, reason, alert_level, explanation)
    VALUES
      ('Testville', 2026, 32, 120.0, 45.0, 5, true, 95.3,
       'Cases are 2.67x the historical average', 'ALERT',
       'Testville reports 120 cases against a 4-year average of 45 - a 2.7x jump with no rainfall change, consistent with an outbreak signal rather than seasonal noise.'),
      ('Testville', 2026, 31, 80.0, 50.0, 5, true, 71.8,
       'Cases are 1.60x the historical average', 'WATCH',
       'Testville cases run 1.6x the historical average this week. The rise is moderate and partly tracks seasonal rainfall; continued monitoring advised before escalation.')
""")
conn.commit()
print("Inserted 2 test rows with explanations")