"""
lambda_flunet_ingest.py
-----------------------
AWS Lambda function — triggered by EventBridge on a scheduled basis.

Pulls WHO FluNet data for one or more countries, then upserts rows into
the season_baseline table in CockroachDB.

Environment variables (set in Lambda configuration):
  SECRET_NAME      – name or full ARN of the Secrets Manager secret that holds
                     the CockroachDB connection string, e.g.
                     "flu-watch/cockroachdb/conn-string"
  AWS_REGION       – AWS region where the secret lives (Lambda sets this
                     automatically; override only if the secret is in a
                     different region than the function)
  COUNTRY_CODE     – single ISO3 country code, e.g. "SGP"
                     Optionally comma-separated for multiple: "SGP,AUS,USA"
  COUNTRY_LABEL    – human-readable label matching COUNTRY_CODE order, e.g.
                     "Singapore" or "Singapore,Australia,United States"
  MIN_YEAR         – earliest ISO_YEAR to fetch (default: 2019)
  API_MAX_RETRIES  – number of retries on transient API errors (default: 3)
  API_RETRY_DELAY  – seconds between retries (default: 5)

Secret format in Secrets Manager (plain-text string):
  postgresql://user:pass@host:26257/dbname?sslmode=verify-full

EventBridge rule example (cron — every Monday at 06:00 UTC):
  cron(0 6 ? * MON *)
"""

import json
import logging
import os
import time

import boto3
import psycopg2
import requests
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Constants / config pulled from environment
# ---------------------------------------------------------------------------
WHO_FLUNET_URL = "https://xmart-api-public.who.int/FLUMART/VIW_FNT"

# Name or ARN of the Secrets Manager secret — the only required env var.
SECRET_NAME = os.environ["SECRET_NAME"]
AWS_REGION  = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# Country config: support a comma-separated list so one Lambda covers multiple regions.
_RAW_CODES   = os.environ.get("COUNTRY_CODE",  "SGP").strip()
_RAW_LABELS  = os.environ.get("COUNTRY_LABEL", "Singapore").strip()
COUNTRY_CODES  = [c.strip() for c in _RAW_CODES.split(",")  if c.strip()]
COUNTRY_LABELS = [l.strip() for l in _RAW_LABELS.split(",") if l.strip()]

if len(COUNTRY_CODES) != len(COUNTRY_LABELS):
    raise ValueError(
        f"COUNTRY_CODE has {len(COUNTRY_CODES)} entries but "
        f"COUNTRY_LABEL has {len(COUNTRY_LABELS)}; they must match."
    )

MIN_YEAR        = int(os.environ.get("MIN_YEAR",         "2019"))
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES",  "3"))
API_RETRY_DELAY = float(os.environ.get("API_RETRY_DELAY", "5"))


# ---------------------------------------------------------------------------
# Secrets Manager — cached across warm Lambda invocations
# ---------------------------------------------------------------------------

# Module-level cache: populated on first invocation, reused on warm starts.
# This avoids a Secrets Manager round-trip on every scheduled execution while
# still picking up rotation on the next cold start.
_secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)
_cached_conn_string: str | None = None


def get_conn_string() -> str:
    """
    Return the CockroachDB connection string from Secrets Manager.

    The result is cached in a module-level variable so warm Lambda invocations
    skip the network call.  If the secret has been rotated, re-deploy or set a
    short Lambda lifetime (< rotation interval) to pick up the new value.
    """
    global _cached_conn_string
    if _cached_conn_string is not None:
        return _cached_conn_string

    logger.info("Fetching connection string from Secrets Manager (secret: %s).", SECRET_NAME)
    try:
        response = _secrets_client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        # Surface actionable messages for the most common misconfiguration errors.
        if error_code == "ResourceNotFoundException":
            raise RuntimeError(
                f"Secret '{SECRET_NAME}' not found. "
                "Check SECRET_NAME env var and the secret's AWS region."
            ) from exc
        if error_code in ("AccessDeniedException", "InvalidRequestException"):
            raise RuntimeError(
                f"Lambda execution role lacks secretsmanager:GetSecretValue "
                f"permission for secret '{SECRET_NAME}': {exc}"
            ) from exc
        raise RuntimeError(f"Secrets Manager error ({error_code}): {exc}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"Boto3 error fetching secret: {exc}") from exc

    # The secret is stored as a plain-text string (not JSON-wrapped).
    secret = response.get("SecretString")
    if not secret:
        raise RuntimeError(
            f"Secret '{SECRET_NAME}' exists but SecretString is empty. "
            "Ensure the secret value is a plain-text connection string."
        )

    _cached_conn_string = secret.strip()
    return _cached_conn_string


# ---------------------------------------------------------------------------
# WHO FluNet API helpers
# ---------------------------------------------------------------------------

def fetch_flunet_rows(country_code: str, min_year: int) -> list[dict]:
    """
    Fetch all FluNet records for *country_code* from *min_year* onwards.

    Retries up to API_MAX_RETRIES times on connection errors or non-200
    responses, with a fixed delay between attempts.

    Returns the list of value dicts from the OData JSON response.
    Raises RuntimeError if all retries are exhausted.
    """
    params = {
        "$filter": f"COUNTRY_CODE eq '{country_code}' and ISO_YEAR ge {min_year}",
        "$format": "json",
    }

    last_exc: Exception | None = None

    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            logger.info(
                "Fetching FluNet data for %s (attempt %d/%d)",
                country_code, attempt, API_MAX_RETRIES,
            )
            response = requests.get(WHO_FLUNET_URL, params=params, timeout=30)
            response.raise_for_status()

            payload = response.json()
            rows = payload.get("value")
            if rows is None:
                raise ValueError(
                    f"Unexpected API response shape — 'value' key missing. "
                    f"Keys present: {list(payload.keys())}"
                )

            logger.info("Fetched %d raw rows for %s.", len(rows), country_code)
            return rows

        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt, API_MAX_RETRIES, country_code, exc,
            )
            if attempt < API_MAX_RETRIES:
                time.sleep(API_RETRY_DELAY)

    raise RuntimeError(
        f"All {API_MAX_RETRIES} attempts to fetch FluNet data for "
        f"{country_code} failed. Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open and return a psycopg2 connection to CockroachDB."""
    return psycopg2.connect(get_conn_string())


def upsert_rows(
    cur,
    rows: list[dict],
    region_label: str,
) -> tuple[int, int]:
    """
    Upsert a list of FluNet API rows for *region_label* into season_baseline.

    Skips rows where INF_ALL is null or unparseable.
    Returns (inserted_or_checked, skipped) counts.
    """
    INSERT_SQL = """
        INSERT INTO season_baseline (region, season_year, epi_week, case_count, source)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (region, season_year, epi_week) DO NOTHING
    """

    inserted = 0
    skipped  = 0

    for row in rows:
        raw_cases = row.get("INF_ALL")
        if raw_cases is None:
            skipped += 1
            continue

        try:
            values = (
                region_label,
                int(row["ISO_YEAR"]),
                int(row["ISO_WEEK"]),
                int(raw_cases),
                "WHO FluNet",
            )
        except (ValueError, TypeError, KeyError) as exc:
            logger.debug("Skipping malformed row %s: %s", row, exc)
            skipped += 1
            continue

        # epi_week must be in the valid WHO range 1–53
        if not (1 <= values[2] <= 53):
            logger.debug("Skipping row with out-of-range epi_week %d: %s", values[2], row)
            skipped += 1
            continue

        cur.execute(INSERT_SQL, values)
        inserted += 1

    return inserted, skipped


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    """
    Lambda entry point.

    EventBridge passes a scheduled event dict; the payload isn't used
    directly — country config comes from environment variables.

    Returns a summary dict so CloudWatch / Step Functions can inspect results.
    """
    logger.info("Lambda invoked. Event: %s", json.dumps(event))

    results = []
    pipeline_errors = []

    for code, label in zip(COUNTRY_CODES, COUNTRY_LABELS):
        country_result = {"country_code": code, "region": label}

        # --- 1. Fetch from WHO API (with retries) ---
        try:
            rows = fetch_flunet_rows(code, MIN_YEAR)
        except RuntimeError as exc:
            # A failed pull for one country should NOT abort the rest.
            logger.error("API pull failed for %s (%s): %s", code, label, exc)
            country_result["status"]  = "API_ERROR"
            country_result["detail"]  = str(exc)
            results.append(country_result)
            pipeline_errors.append(code)
            continue

        # --- 2. Write to CockroachDB ---
        conn = None
        try:
            conn = get_db_connection()
            cur  = conn.cursor()

            inserted, skipped = upsert_rows(cur, rows, label)

            conn.commit()
            logger.info(
                "%s: upserted %d rows, skipped %d rows.",
                label, inserted, skipped,
            )
            country_result["status"]   = "OK"
            country_result["inserted"] = inserted
            country_result["skipped"]  = skipped

        except psycopg2.Error as exc:
            logger.error("DB error for %s: %s", label, exc)
            if conn:
                try:
                    conn.rollback()
                except psycopg2.Error:
                    pass
            country_result["status"] = "DB_ERROR"
            country_result["detail"] = str(exc)
            pipeline_errors.append(code)

        finally:
            if conn:
                try:
                    conn.close()
                except psycopg2.Error:
                    pass

        results.append(country_result)

    # --- 3. Build response ---
    overall_status = "ERROR" if pipeline_errors else "OK"
    if pipeline_errors and len(pipeline_errors) < len(COUNTRY_CODES):
        overall_status = "PARTIAL_ERROR"

    response = {
        "status":           overall_status,
        "countries_ok":     [r["country_code"] for r in results if r.get("status") == "OK"],
        "countries_failed": pipeline_errors,
        "details":          results,
    }

    logger.info("Run complete. Summary: %s", json.dumps(response))

    # Raise on total failure so EventBridge / Lambda retries kick in.
    if overall_status == "ERROR":
        raise RuntimeError(
            f"All country pulls failed: {pipeline_errors}. "
            "See CloudWatch logs for details."
        )

    return response
