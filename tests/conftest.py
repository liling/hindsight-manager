import os

# Set required env vars before any test module imports the app.
# Settings() is called at module level in proxy.py, so these must be
# available before `from hindsight_manager.main import app`.
os.environ.setdefault("HINDSIGHT_MANAGER_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("HINDSIGHT_MANAGER_JWT_SECRET", "test-secret-for-manager")
os.environ.setdefault("HINDSIGHT_MANAGER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
