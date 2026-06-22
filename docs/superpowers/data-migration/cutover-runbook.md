# HM ↔ xinyi-platform Cutover Runbook (Plan B Phase 4)

**Window:** Saturday 02:00 (low traffic). Allow 30 min total.

## Pre-flight (T-24h)

- [ ] Dry-run data migration SQL on staging: see `docs/superpowers/data-migration/README.md`
- [ ] Confirm `xinyi-platform` is deployed and reachable at `http://xinyi-platform:8000` from HM container
- [ ] Generate hm-prod client secret + bcrypt hash; store RAW in HM secrets, HASH ready to insert
- [ ] Build HM image from `feat/xinyi-platform-hm-refactor` branch
- [ ] Prepare rollback image: HM image from `master` (pre-refactor)
- [ ] Notify users of 15-min outage + forced re-login

## Cutover steps (T+0 onward)

```
T+0:00  Stop HM + control-plane services:
          docker-compose stop hindsight-manager control-plane
T+0:01  Backup Postgres (pg_dump manager schema at minimum)
T+0:03  Run data migration SQL (from docs/superpowers/data-migration/):
          psql "$DATABASE_URL" -f 001_import_users_to_xinyi.sql
          psql "$DATABASE_URL" -f 002_import_audit_logs_to_xinyi.sql
          psql "$DATABASE_URL" -f 003_import_login_history_to_xinyi.sql
          psql "$DATABASE_URL" -f 004_import_email_verifications_to_xinyi.sql
          psql "$DATABASE_URL" -v client_secret_hash="'\$2b\$12\$....'" -f 005_register_hm_prod_client.sql
T+0:05  Verify row counts match (queries in each script's tail)
T+0:06  Start xinyi-platform service (already running, but verify health)
          curl http://xinyi-platform:8000/health → {"status":"ok"}
T+0:07  Apply HM Alembic migration 006 (audit_outbox):
          docker-compose run --rm hindsight-manager alembic upgrade head
T+0:08  Start refactored HM image
T+0:09  Smoke test:
          - Browser → http://hm:8001/admin/tenants → expect 302 to /auth/login-redirect
          - Follow redirect → arrive at xinyi-platform login page
          - Login as admin → callback to HM → cookie set → back at /admin/tenants
T+0:12  Start control-plane
T+0:13  Smoke test OTP flow → control plane SSO
T+0:15  All clear
```

## Rollback (if smoke test fails)

```
T+??:  Stop new HM image
       docker-compose stop hindsight-manager
       Pull previous HM image (master)
       docker-compose start hindsight-manager
       (manager.* tables still intact — 007 was NOT run, so no data loss)
       Verify HM works standalone (legacy login reactivated)
```

## Phase 5 (T+2 weeks)

After 2 weeks of stable operation, run migration 007 to **rename** legacy
`manager.users` / `audit_logs` / `login_history` / `email_verifications` tables:

```
docker-compose run --rm hindsight-manager alembic upgrade 007
```

007 appends `_deprecated` suffix to each table (no data loss). Keep these
around as long as desired — they cost only disk space and don't conflict
with running code (HM no longer references them).

Restoring state: `alembic downgrade 007` (renames `users_deprecated` back to `users`).

Pre-flight for Phase 5:
- [ ] Confirm no business endpoint queries `manager.users` directly (should be zero after Plan B refactor)
- [ ] Confirm `manager.audit_logs`/`login_history`/`email_verifications` empty (they should have been drained into xinyi.*)
- [ ] Backup once more before renaming

Post-Phase-5 state:
- `manager` schema contains only: `tenants`, `tenant_members`, `api_keys`, `audit_outbox`, plus `*_deprecated` tables
- `xinyi` schema is the source of truth for users/audit/auth

If you later want to physically DROP the `*_deprecated` tables (after long-term
confidence), it's a manual DBA operation — no tooling here on purpose, to prevent
accidental data loss.