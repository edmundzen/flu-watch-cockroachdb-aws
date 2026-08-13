# Secrets Manager setup for the FluNet Lambda

## 1. Create the secret

The Lambda reads a **plain-text** secret (not a key/value JSON map).
The value is the full psycopg2 connection string for CockroachDB.

### AWS CLI

```bash
aws secretsmanager create-secret \
  --name "flu-watch/cockroachdb/conn-string" \
  --description "CockroachDB connection string for the FluNet Lambda" \
  --secret-string "postgresql://user:pass@host:26257/dbname?sslmode=verify-full" \
  --region us-east-1
```

> Swap `user`, `pass`, `host`, `dbname`, and `--region` for your real values.
> CockroachDB Serverless clusters use port **26257** and require `sslmode=verify-full`.

### AWS Console (alternative)

1. Open **Secrets Manager → Store a new secret**.
2. Choose **Other type of secret**.
3. Under *Plaintext*, paste the connection string directly (no JSON wrapper).
4. Name it `flu-watch/cockroachdb/conn-string`.
5. Leave rotation disabled for now; enable it later once you have a rotation Lambda.

---

## 2. Update the secret value (rotation / credential change)

```bash
aws secretsmanager put-secret-value \
  --secret-id "flu-watch/cockroachdb/conn-string" \
  --secret-string "postgresql://newuser:newpass@host:26257/dbname?sslmode=verify-full"
```

Because the Lambda caches the connection string for the lifetime of a warm
execution environment, **redeploy or force a cold start** after rotation so
the new value is picked up immediately. The simplest way to force a cold start:

```bash
aws lambda update-function-configuration \
  --function-name flunet-ingest \
  --environment "Variables={SECRET_NAME=flu-watch/cockroachdb/conn-string,COUNTRY_CODE=SGP,COUNTRY_LABEL=Singapore}"
```

(Any configuration change triggers a new execution environment.)

---

## 3. Grant the Lambda execution role permission

The Lambda's IAM execution role needs exactly one Secrets Manager permission.
Attach an inline policy (or a managed policy) to the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowFluWatchSecretRead",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:flu-watch/cockroachdb/conn-string-*"
    }
  ]
}
```

Replace `us-east-1` and `ACCOUNT_ID` with your values.
The trailing `-*` wildcard covers the random suffix that Secrets Manager appends
to the ARN (e.g. `…conn-string-aBcDeF`).

### Via AWS CLI

```bash
aws iam put-role-policy \
  --role-name flunet-lambda-execution-role \
  --policy-name FluWatchSecretRead \
  --policy-document file://iam_secret_policy.json
```

---

## 4. Set the Lambda environment variable

The only credential-related env var the Lambda now needs is the secret name:

| Variable | Value |
|---|---|
| `SECRET_NAME` | `flu-watch/cockroachdb/conn-string` |

All other env vars (`COUNTRY_CODE`, `COUNTRY_LABEL`, `MIN_YEAR`, etc.) are
non-sensitive and can stay as plain Lambda environment variables.

```bash
aws lambda update-function-configuration \
  --function-name flunet-ingest \
  --environment "Variables={
    SECRET_NAME=flu-watch/cockroachdb/conn-string,
    COUNTRY_CODE=SGP,
    COUNTRY_LABEL=Singapore,
    MIN_YEAR=2019
  }"
```

---

## 5. Verify end-to-end

Invoke the Lambda once manually and check CloudWatch logs:

```bash
aws lambda invoke \
  --function-name flunet-ingest \
  --payload '{}' \
  --log-type Tail \
  response.json \
  | python -c "import sys,json,base64; body=json.load(sys.stdin); print(base64.b64decode(body['LogResult']).decode())"
```

A successful cold start will log:
```
Fetching connection string from Secrets Manager (secret: flu-watch/cockroachdb/conn-string).
Fetching FluNet data for SGP (attempt 1/3)
Fetched N raw rows for SGP.
Singapore: upserted N rows, skipped M rows.
Run complete. Summary: {"status": "OK", ...}
```

Subsequent warm invocations will skip the Secrets Manager call entirely.
