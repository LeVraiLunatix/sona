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
