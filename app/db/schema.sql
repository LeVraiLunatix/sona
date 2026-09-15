CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    quality TEXT NOT NULL DEFAULT 'best',
    format TEXT NOT NULL DEFAULT 'auto',
    notifications INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('track', 'album', 'artist')),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT,
    cover_url TEXT,
    added_at TEXT NOT NULL,
    UNIQUE (user_id, kind, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_library_lookup ON library (user_id, kind, added_at DESC);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT,
    cover_url TEXT,
    viewed_at TEXT NOT NULL,
    UNIQUE (user_id, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_history_lookup ON history (user_id, viewed_at DESC);

CREATE TABLE IF NOT EXISTS audio_cache (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    format TEXT NOT NULL,
    quality TEXT NOT NULL,
    telegram_file_id TEXT NOT NULL,
    telegram_file_unique_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, format, quality)
);

CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY,
    display_name TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    added_by INTEGER,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER,
    used_at TEXT,
    max_uses INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS access_requests (
    user_id INTEGER PRIMARY KEY,
    display_name TEXT,
    username TEXT,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_by INTEGER,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_access_requests_status ON access_requests (status, requested_at DESC);
