# Data Migration: manager.* → xinyi.*

One-shot SQL migration copying HM infrastructure tables into xinyi-platform's schema.
Runs after `xinyi-platform` Alembic migrations have created the `xinyi` schema + tables.

## Prerequisites

1. xinyi-platform deployed with `uv run alembic upgrade head` run (Plan A complete)
2. HM stopped (or in read-only mode) during migration window
3. `psql` access to the shared Postgres

## Dry-run (staging)

Wrap each script in a transaction and ROLLBACK to preview without committing:

```bash
psql "$DATABASE_URL" <<EOF
BEGIN;
\i docs/superpowers/data-migration/001_import_users_to_xinyi.sql
\i docs/superpowers/data-migration/002_import_audit_logs_to_xinyi.sql
\i docs/superpowers/data-migration/003_import_login_history_to_xinyi.sql
\i docs/superpowers/data-migration/004_import_email_verifications_to_xinyi.sql
SELECT 'users diff:',
       (SELECT count(*) FROM manager.users) - (SELECT count(*) FROM xinyi.users);
SELECT 'audit_logs diff:',
       (SELECT count(*) FROM manager.audit_logs) - (SELECT count(*) FROM xinyi.audit_logs);
SELECT 'login_history diff:',
       (SELECT count(*) FROM manager.login_history) - (SELECT count(*) FROM xinyi.login_history);
SELECT 'email_verifications diff:',
       (SELECT count(*) FROM manager.email_verifications) - (SELECT count(*) FROM xinyi.email_verifications);
ROLLBACK;
EOF
```

All diffs must be 0.

## Production cutover

See `cutover-runbook.md` (Plan B Task 13).

## Generating hm-prod client secret

```bash
python -c "import secrets, bcrypt; s=secrets.token_urlsafe(32); print('RAW:', s); print('HASH:', bcrypt.hashpw(s.encode(), bcrypt.gensalt(rounds=12)).decode())"
```

- Paste RAW into HM's `.env` as `HINDSIGHT_MANAGER_OAUTH_CLIENT_SECRET=<raw>`
- Paste HASH into `005_register_hm_prod_client.sql` replacing `:client_secret_hash` (wrap in single quotes)

Example psql invocation:

```bash
psql "$DATABASE_URL" -v client_secret_hash="'\$2b\$12\$....'" -f docs/superpowers/data-migration/005_register_hm_prod_client.sql
```
