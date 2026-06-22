-- Register hm-prod business client in xinyi-platform.
-- IMPORTANT: substitute :client_secret_hash with a real bcrypt hash before running.
-- Generate secret + hash:
--   python -c "import secrets, bcrypt; s=secrets.token_urlsafe(32); print('RAW:', s); print('HASH:', bcrypt.hashpw(s.encode(), bcrypt.gensalt(rounds=12)).decode())"
-- Store RAW in hindsight-manager's .env as HINDSIGHT_MANAGER_OAUTH_CLIENT_SECRET.

INSERT INTO xinyi.business_clients (
    id, client_id, name, client_secret_hash, redirect_uris, status, created_at, updated_at
)
VALUES (
    gen_random_uuid(),
    'hm-prod',
    'Hindsight Manager',
    :client_secret_hash,
    '["http://localhost:8001/auth/callback", "http://hm:8001/auth/callback"]'::jsonb,
    'active',
    now(),
    now()
)
ON CONFLICT (client_id) DO NOTHING;

SELECT client_id, name, status FROM xinyi.business_clients WHERE client_id = 'hm-prod';
