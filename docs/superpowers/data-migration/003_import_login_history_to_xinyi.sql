INSERT INTO xinyi.login_history (
    id, user_id, ip_address, user_agent, login_time, success, failure_reason
)
SELECT
    h.id, h.user_id, h.ip_address, h.user_agent,
    h.login_time, h.success, h.failure_reason
FROM manager.login_history h
ON CONFLICT (id) DO NOTHING;

SELECT 'manager.login_history count:', count(*) FROM manager.login_history
UNION ALL
SELECT 'xinyi.login_history count:', count(*) FROM xinyi.login_history;
