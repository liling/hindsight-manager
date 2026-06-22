-- Copy manager.audit_logs → xinyi.audit_logs
-- client_id is new in xinyi.audit_logs — set to 'hm-prod' for backfilled rows

INSERT INTO xinyi.audit_logs (
    id, user_id, client_id, action, resource_type, resource_id,
    detail, ip_address, created_at
)
SELECT
    a.id,
    a.user_id,
    'hm-prod',
    a.action,
    a.resource_type,
    a.resource_id,
    a.detail,
    a.ip_address,
    a.created_at
FROM manager.audit_logs a
ON CONFLICT (id) DO NOTHING;

SELECT 'manager.audit_logs count:', count(*) FROM manager.audit_logs
UNION ALL
SELECT 'xinyi.audit_logs count:', count(*) FROM xinyi.audit_logs;
