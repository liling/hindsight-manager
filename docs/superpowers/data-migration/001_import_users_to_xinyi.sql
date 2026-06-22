-- Copy manager.users → xinyi.users
-- Idempotent: ON CONFLICT DO NOTHING allows safe rerun
-- Note: xinyi.users.created_at is TIMESTAMPTZ; manager.users.created_at may be string (legacy)

INSERT INTO xinyi.users (
    id, username, email, password_hash, display_name,
    auth_provider, role, is_active, last_login_at,
    created_at, updated_at
)
SELECT
    u.id,
    u.username,
    u.email,
    u.password_hash,
    u.display_name,
    (CASE u.auth_provider::text WHEN 'local' THEN 'local' WHEN 'cas' THEN 'cas' ELSE 'local' END)::xinyi.auth_provider,
    (CASE u.role::text WHEN 'admin' THEN 'admin' ELSE 'user' END)::xinyi.user_role,
    u.is_active,
    u.last_login_at,
    (u.created_at)::timestamptz,
    u.updated_at
FROM manager.users u
ON CONFLICT (id) DO NOTHING;

-- Verify
SELECT 'manager.users count:', count(*) FROM manager.users
UNION ALL
SELECT 'xinyi.users count:', count(*) FROM xinyi.users;
