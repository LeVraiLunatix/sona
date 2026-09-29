CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    quality TEXT NOT NULL DEFAULT 'best',
    format TEXT NOT NULL DEFAULT 'auto',
    notifications INTEGER NOT NULL DEFAULT 1,
    autoplay INTEGER NOT NULL DEFAULT 1,
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
    -- Fiche complète d'un titre (JSON) : la bibliothèque se relit sans
    -- redemander chaque titre au catalogue.
    data TEXT,
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

-- Fichiers audio conservés sur disque pour l'API (app iOS) : contrairement au
-- cache Telegram (audio_cache), qui ne garde qu'un file_id distant, ici c'est
-- le fichier lui-même qui doit rester disponible pour être re-streamé.
CREATE TABLE IF NOT EXISTS stream_cache (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    format TEXT NOT NULL,
    quality TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
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

-- Écoutes réelles (« scrobbles ») : une ligne par morceau écouté assez
-- longtemps dans l'app (moitié du titre ou 4 min, la règle de Last.fm), ou
-- importé depuis l'historique Last.fm (origin = 'lastfm'). Base des stats
-- d'écoute de l'app — à ne pas confondre avec `history` (fiches consultées).
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    played_at TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    source TEXT,
    source_id TEXT,
    artist_source_id TEXT,
    album_source_id TEXT,
    cover_url TEXT,
    duration_seconds INTEGER,
    listened_seconds INTEGER,
    origin TEXT NOT NULL DEFAULT 'sona',
    UNIQUE (user_id, played_at, title, artist)
);
CREATE INDEX IF NOT EXISTS idx_plays_user_time ON plays (user_id, played_at);

-- Comptes de l'app iOS, connectés avec Last.fm. Un compte n'accède à l'app
-- qu'une fois accepté par un admin (status = 'approved'). `user_id` est
-- l'espace de données du compte (bibliothèque, historique, réglages,
-- écoutes) : le premier admin reprend celui de l'ancien jeton unique
-- (API_USER_ID) pour garder ses données.
CREATE TABLE IF NOT EXISTS app_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lastfm_username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT,
    avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    is_admin INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER NOT NULL UNIQUE,
    lastfm_session_key TEXT,
    scrobble_to_lastfm INTEGER NOT NULL DEFAULT 1,
    share_listening INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by INTEGER
);

-- Sessions de l'app : seule l'empreinte SHA-256 du jeton est stockée.
CREATE TABLE IF NOT EXISTS app_sessions (
    token_hash TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_sessions_account ON app_sessions (account_id);

-- Playlists de l'app : créées à la main ou importées (Deezer, Spotify,
-- Apple Music). Pendant un import, `import_status` vaut 'importing' et
-- `import_done` / `import_total` donnent l'avancement à l'app.
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    cover_url TEXT,
    origin TEXT,
    origin_url TEXT,
    import_status TEXT NOT NULL DEFAULT 'done',
    import_total INTEGER,
    import_done INTEGER NOT NULL DEFAULT 0,
    import_missing INTEGER NOT NULL DEFAULT 0,
    import_error TEXT,
    visibility TEXT NOT NULL DEFAULT 'private',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_playlists_user ON playlists (user_id, updated_at DESC);

-- Morceaux d'une playlist, recopiés tels quels (pas de nouvelle requête au
-- catalogue pour l'afficher). Un même titre peut y figurer deux fois : une
-- entrée s'identifie par son `id`, pas par le morceau.
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    year TEXT,
    duration_seconds INTEGER,
    cover_url TEXT,
    artist_source_id TEXT,
    album_source_id TEXT,
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_order ON playlist_tracks (playlist_id, position);

-- Source audio (vidéo YouTube, piste SoundCloud) servie pour chaque morceau
-- — celle du fichier en cache, ou du flux direct —, et celles signalées
-- comme « mauvaise version » depuis l'app (clip, live...), jamais reprises.
CREATE TABLE IF NOT EXISTS stream_sources (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS rejected_sources (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, video_id)
);

-- Écrans associés pour « Écouter sur la TV / PS5 » (appli YouTube pilotée
-- à distance, voir services/tv_cast.py).
CREATE TABLE IF NOT EXISTS tv_screens (
    user_id INTEGER NOT NULL,
    screen_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lounge_token TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, screen_id)
);

-- Blind test : un score par partie ; le défi du jour (mode 'daily') est le
-- même pour tout le monde, classement du jour.
CREATE TABLE IF NOT EXISTS blindtest_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    day TEXT NOT NULL,
    score INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blindtest_day ON blindtest_scores (mode, day, score DESC);

-- Analyse audio d'un titre en cache (AutoMix) : sonie intégrée (LUFS),
-- début réel, moment de l'outro, fin réelle — en secondes.
CREATE TABLE IF NOT EXISTS track_analysis (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    loudness REAL NOT NULL,
    start REAL NOT NULL,
    mix_out REAL NOT NULL,
    end_time REAL NOT NULL,
    duration REAL NOT NULL,
    analyzed_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
