-- Flu Watch — CockroachDB schema
-- Season baseline store: multi-year WHO FluNet history, keyed by region/season/week.
-- Nitish's Lambda writes here; Aadi's anomaly scoring reads "this season vs. baseline" from here.

CREATE TABLE season_baseline (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  region TEXT NOT NULL,
  season_year INT NOT NULL,
  epi_week INT NOT NULL,        -- WHO epidemiological week, 1-53
  case_count INT,
  rain_mm FLOAT,
  source TEXT DEFAULT 'WHO FluNet',
  embedding VECTOR(768),        -- for Distributed Vector Indexing
  ingested_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (region, season_year, epi_week)
);

-- Distributed Vector Indexing — one of the two required CockroachDB tools for this hackathon.
-- Note: on CockroachDB Basic tier, the vector index feature is already enabled by default
-- (v25.4+). Do NOT run `SET CLUSTER SETTING feature.vector_index.enabled = true` — it is
-- blocked with "disallowed statement type" on Basic tier. Just run the CREATE VECTOR INDEX
-- statement directly.
CREATE VECTOR INDEX ON season_baseline (embedding);

COMMENT ON TABLE season_baseline IS 'Multi-year FluNet baseline — Lambda writes here; anomaly scoring queries this-season-vs-baseline';

-- anomaly_results — populated by the anomaly-scoring pipeline (Aadi).
-- Compares latest epi week case count against historical average for the same region,
-- excluding the current season from the baseline, and tiers the result.
CREATE TABLE anomaly_results (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  region TEXT NOT NULL,
  season_year INT NOT NULL,
  epi_week INT NOT NULL,
  case_count INT,
  historical_avg FLOAT,
  ratio FLOAT,
  tier TEXT,                     -- NORMAL / WATCH / ALERT
  explanation TEXT,              -- filled in by Bedrock
  reviewed_by TEXT,               -- human approver, filled in by the approval UI
  reviewed_at TIMESTAMPTZ,
  decision TEXT,                  -- APPROVED / REJECTED
  created_at TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE anomaly_results IS 'Scored anomalies + Bedrock explanation + human approval decision, forming the audit log';
