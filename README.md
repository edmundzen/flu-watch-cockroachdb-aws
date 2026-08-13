# Flu Watch — AWS × CockroachDB Sentinel

Flu Watch turns WHO FluNet history into memory: CockroachDB holds multi-year season baselines, Bedrock explains anomalies in plain English, a human approves every alert.

Built by **Team Cloud Catalyst** for the CockroachDB × AWS Hackathon — Build with Agentic Memory (submit by Aug 18, 2026, 5:00pm EDT).

## Architecture

```
WHO FluNet API → AWS Lambda (scheduled pull) → CockroachDB season store
  → anomaly scan (this season vs. baseline) → AWS Bedrock (plain-English explanation)
  → human approves/rejects → alert issued → decision logged back to CockroachDB
```

Pattern: **Remember → Detect → Recommend → Human Approves → Act → Log** — reused from our earlier Dengue Sentinel and FinOps Sentinel projects.

## CockroachDB tools used (≥2 required)

- **Managed MCP Server** — the anomaly-detection agent queries the season store directly through CockroachDB's MCP server as a tool.
- **Distributed Vector Indexing** — `CREATE VECTOR INDEX` on `season_baseline.embedding`, enabling similarity search over historical patterns.

## AWS services used (≥1 required)

- **AWS Lambda** — scheduled ingestion of WHO FluNet data into CockroachDB.
- **AWS Bedrock** (Claude Haiku 4.5) — turns a scored anomaly into a plain-English root-cause explanation for the human reviewer.

## Data

Real historical influenza surveillance data pulled directly from WHO's public FluNet API (`https://xmart-api-public.who.int/FLUMART/VIW_FNT`), no authentication required. Currently loaded: 294 weekly records for Singapore, 2019–present.

## Repo contents

- `schema.sql` — CockroachDB schema: `season_baseline` (multi-year baseline) and `anomaly_results` (scored anomalies + Bedrock explanation + human decision, forming the audit log).
- `load_flunet.py` — pulls historical WHO FluNet data and loads it into `season_baseline`.
- `insert_test.py` — minimal write-path proof/example insert.

## Setup

1. Create a CockroachDB Cloud cluster (Basic/Serverless tier, free).
2. Run `schema.sql` against your cluster via the SQL Shell or `psql`.
3. Set `COCKROACH_CONN` as an environment variable to your cluster's connection string.
4. Run `python load_flunet.py` to pull and load real FluNet data for a given country.

## Team

Edmund (CockroachDB + orchestration) · Aadi (anomaly detection + scoring) · Nitish (AWS Lambda + Bedrock) · Nandini (human-approval UI + demo)
