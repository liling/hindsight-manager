INSERT INTO xinyi.email_verifications (
    id, email, code, purpose, expires_at, verified, attempts, created_at
)
SELECT
    e.id, e.email, e.code, e.purpose, e.expires_at,
    e.verified, e.attempts, e.created_at
FROM manager.email_verifications e
ON CONFLICT (id) DO NOTHING;

SELECT 'manager.email_verifications count:', count(*) FROM manager.email_verifications
UNION ALL
SELECT 'xinyi.email_verifications count:', count(*) FROM xinyi.email_verifications;
