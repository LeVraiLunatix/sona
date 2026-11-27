use crate::auth::Authenticator;
use crate::config::Config;
use crate::crypto::Vault;
use crate::jwt::JwtVerifier;
use sqlx::PgPool;
use std::sync::Arc;
use webauthn_rs::Webauthn;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub pool: PgPool,
    pub auth: Arc<Authenticator>,
    pub vault: Option<Arc<Vault>>,
    pub http: reqwest::Client,
    pub webauthn: Option<Arc<Webauthn>>,
    /// Surchargeable en test (faux serveur Last.fm).
    pub lastfm_base: Arc<String>,
}

impl AppState {
    pub fn new(cfg: Config, pool: PgPool) -> Self {
        let jwks = Some(format!("{}/auth/v1/.well-known/jwks.json", cfg.supabase_url));
        let jwt = Arc::new(JwtVerifier::new(cfg.jwt_secret.as_deref(), jwks));
        Self::with_verifier(cfg, pool, jwt)
    }

    pub fn with_verifier(cfg: Config, pool: PgPool, jwt: Arc<JwtVerifier>) -> Self {
        let vault = cfg.secrets_key.as_deref().and_then(|k| Vault::from_base64(k).ok()).map(Arc::new);
        let webauthn = build_webauthn(&cfg);
        let auth = Arc::new(Authenticator::new(pool.clone(), jwt, cfg.status_cache_ttl));
        AppState {
            http: reqwest::Client::builder().timeout(std::time::Duration::from_secs(10)).build().expect("client HTTP"),
            cfg: Arc::new(cfg),
            pool,
            auth,
            vault,
            webauthn,
            lastfm_base: Arc::new("https://ws.audioscrobbler.com/2.0/".into()),
        }
    }
}

fn build_webauthn(cfg: &Config) -> Option<Arc<Webauthn>> {
    let (id, origin) = (cfg.webauthn_rp_id.as_deref()?, cfg.webauthn_origin.as_deref()?);
    let url = url::Url::parse(origin).ok()?;
    let builder = webauthn_rs::WebauthnBuilder::new(id, &url).ok()?;
    builder.rp_name("Sona").build().ok().map(Arc::new)
}
