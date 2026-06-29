"""Test-wide configuration.

Point the app at an isolated on-disk SQLite database (async) so integration tests need no
Postgres. This MUST run before `config`/`database` are imported, because the SQLAlchemy engine
is built from `settings.database_url` at import time. pytest imports conftest before any test
module, so setting the env var here is early enough.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/test_portfaio.db"
