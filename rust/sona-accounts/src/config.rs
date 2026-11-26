//! Configuration, lue dans l'environnement. Aucun secret dans le dépôt : voir `.env.example`.

use std::time::Duration;

#[derive(Clone, Debug)]
pub struct Config {
    pub bind: String,
    /// Connexion Postgres du rôle serveur (pooler Supabase ou direct). Ne quitte jamais le serveur.
    pub database_url: String,
    pub supabase_url: String,
    /// Clé « service role » : seulement pour l'API admin d'Auth (lien magique des passkeys).
    pub supabase_service_key: Option<String>,
    /// Secret JWT (HS256, anciens projets). Sinon les clés publiques sont lues sur le JWKS.
    pub jwt_secret: Option<String>,
    pub cors_origins: Vec<String>,
    /// Adresses de retour autorisées (Last.fm, deep links) : jamais de redirection libre.
    pub allowed_return_urls: Vec<String>,
    pub lastfm_api_key: Option<String>,
    pub lastfm_api_secret: Option<String>,
    /// 32 octets en base64 : chiffre les clés de session des services connectés.
    pub secrets_key: Option<String>,
    /// Secret partagé avec le serveur musique (en-tête `x-sona-internal`).
    pub internal_secret: Option<String>,
    /// Adresse interne du serveur musique (export, suppression, masquage de playlist).
    pub music_internal_url: Option<String>,
    pub hook_secret: Option<String>,
    pub discord_webhook: Option<String>,
    pub webauthn_rp_id: Option<String>,
    pub webauthn_origin: Option<String>,
    pub status_cache_ttl: Duration,
}

fn var(name: &str) -> Option<String> {
    std::env::var(name).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

fn list(name: &str) -> Vec<String> {
    var(name).map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()).unwrap_or_default()
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        Ok(Config {
            bind: var("ACCOUNTS_BIND").unwrap_or_else(|| "127.0.0.1:8100".into()),
            database_url: var("DATABASE_URL").ok_or("DATABASE_URL manquant")?,
            supabase_url: var("SUPABASE_URL").ok_or("SUPABASE_URL manquant")?.trim_end_matches('/').to_string(),
            supabase_service_key: var("SUPABASE_SERVICE_ROLE_KEY"),
            jwt_secret: var("SUPABASE_JWT_SECRET"),
            cors_origins: list("CORS_ORIGINS"),
            allowed_return_urls: list("ALLOWED_RETURN_URLS"),
            lastfm_api_key: var("LASTFM_API_KEY"),
            lastfm_api_secret: var("LASTFM_API_SECRET"),
            secrets_key: var("SECRETS_ENCRYPTION_KEY"),
            internal_secret: var("INTERNAL_API_SECRET"),
            music_internal_url: var("MUSIC_INTERNAL_URL").map(|u| u.trim_end_matches('/').to_string()),
            hook_secret: var("AUTH_HOOK_SECRET"),
            discord_webhook: var("ALERTS_DISCORD_WEBHOOK"),
            webauthn_rp_id: var("WEBAUTHN_RP_ID"),
            webauthn_origin: var("WEBAUTHN_ORIGIN"),
            status_cache_ttl: Duration::from_secs(var("STATUS_CACHE_SECONDS").and_then(|v| v.parse().ok()).unwrap_or(5)),
        })
    }

    /// Configuration minimale pour les tests.
    pub fn for_tests(database_url: &str) -> Self {
        Config {
            bind: "127.0.0.1:0".into(),
            database_url: database_url.into(),
            supabase_url: "https://test.supabase.invalid".into(),
            supabase_service_key: None,
            jwt_secret: Some("test-secret-test-secret-test-secret-32".into()),
            cors_origins: vec![],
            allowed_return_urls: vec!["https://trysona.fr".into(), "http://localhost:8000".into(), "sona://auth/callback".into()],
            lastfm_api_key: Some("clefake".into()),
            lastfm_api_secret: Some("secretfake".into()),
            secrets_key: Some("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=".into()),
            internal_secret: Some("internal-test-secret".into()),
            music_internal_url: None,
            hook_secret: Some("v1,whsec_dGVzdC1ob29rLXNlY3JldA==".into()),
            discord_webhook: None,
            webauthn_rp_id: Some("localhost".into()),
            webauthn_origin: Some("http://localhost:8000".into()),
            status_cache_ttl: Duration::from_secs(0),
        }
    }
}
