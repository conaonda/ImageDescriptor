"""Initial schema: cache table."""

SQL_UP = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at REAL
);
"""
