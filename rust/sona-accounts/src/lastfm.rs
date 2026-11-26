//! Last.fm (optionnel) : connexion, déconnexion, scrobbling.
//!
//! * L'échange `auth.getSession` (qui exige le secret de l'application) se fait
//!   ICI, jamais dans un client. La clé de session est chiffrée (AES-256-GCM,
//!   liée au compte) dans `connected_services`.
//! * Le serveur musique signale chaque écoute à `/internal/scrobble` : elle est
//!   mise en file d'attente PERSISTANTE (`private.scrobble_queue`) puis envoyée
//!   par lot, avec réessais et attente croissante. Une panne de Last.fm, du
//!   réseau ou un redémarrage ne perd rien.
//! * Erreurs traduites en messages clairs (clé révoquée, limite de débit…).

use crate::auth::{AuthAny, AuthUser, Internal};
use crate::error::{AppError, Result};
use crate::lastfm_sig::sign;
use crate::ratelimit;
use crate::redirect::is_allowed_return_url;
use crate::state::AppState;
use axum::extract::{Path, State};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use uuid::Uuid;

pub const AUTH_URL: &str = "https://www.last.fm/api/auth/";

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum LastfmError {
    #[error("Autorise d'abord Sona sur la page Last.fm, puis réessaie.")]
    TokenNotAuthorized,
    #[error("Ce lien de connexion a expiré : relance la connexion à Last.fm.")]
    TokenInvalid,
    #[error("Last.fm a révoqué l'accès de Sona à ton compte : reconnecte-toi.")]
    SessionRevoked,
    #[error("Last.fm limite les requêtes pour le moment : Sona réessaiera tout seul.")]
    RateLimited,
    #[error("Last.fm est momentanément indisponible : Sona réessaiera tout seul.")]
    Temporary,
    #[error("Last.fm a refusé la requête ({0}).")]
    Rejected(String),
    #[error("Last.fm est injoignable.")]
    Network,
}

impl LastfmError {
    fn from_code(code: i64, message: &str) -> Self {
        match code {
            14 => LastfmError::TokenNotAuthorized,
            4 | 15 => LastfmError::TokenInvalid,
            9 | 17 => LastfmError::SessionRevoked,
            29 => LastfmError::RateLimited,
            11 | 16 => LastfmError::Temporary,
            _ => LastfmError::Rejected(format!("code {code} : {}", message.chars().take(120).collect::<String>())),
        }
    }
    /// Vaut-il la peine de réessayer plus tard ?
    pub fn retryable(&self) -> bool {
        matches!(self, LastfmError::RateLimited | LastfmError::Temporary | LastfmError::Network)
    }
}

impl From<LastfmError> for AppError {
    fn from(e: LastfmError) -> Self {
        match e {
            LastfmError::TokenNotAuthorized | LastfmError::TokenInvalid | LastfmError::SessionRevoked => AppError::BadRequest(e.to_string()),
            LastfmError::RateLimited => AppError::RateLimited,
            other => AppError::Upstream(other.to_string()),
        }
    }
}

pub struct Client<'a> {
    pub http: &'a reqwest::Client,
    pub base: &'a str,
    pub key: &'a str,
    pub secret: &'a str,
}

impl Client<'_> {
    pub async fn call(&self, method: &str, mut params: BTreeMap<String, String>, post: bool) -> std::result::Result<Value, LastfmError> {
        params.insert("method".into(), method.into());
        params.insert("api_key".into(), self.key.into());
        let sig = sign(&params, self.secret);
        params.insert("api_sig".into(), sig);
        params.insert("format".into(), "json".into());
        let req = if post { self.http.post(self.base).form(&params) } else { self.http.get(self.base).query(&params) };
        let resp = req.send().await.map_err(|_| LastfmError::Network)?;
        let status = resp.status();
        let body: Value = resp.json().await.map_err(|_| if status.is_server_error() { LastfmError::Temporary } else { LastfmError::Network })?;
        if let Some(code) = body.get("error").and_then(Value::as_i64) {
            return Err(LastfmError::from_code(code, body.get("message").and_then(Value::as_str).unwrap_or("")));
        }
        if status.is_server_error() {
            return Err(LastfmError::Temporary);
        }
        Ok(body)
    }
}

fn client(s: &AppState) -> Result<Client<'_>> {
    match (&s.cfg.lastfm_api_key, &s.cfg.lastfm_api_secret) {
        (Some(key), Some(secret)) => Ok(Client { http: &s.http, base: &s.lastfm_base, key, secret }),
        _ => Err(AppError::NotConfigured("LASTFM_API_KEY / LASTFM_API_SECRET")),
    }
}

// ── Connexion ────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct StartIn {
    pub return_to: String,
}

/// Adresse d'autorisation Last.fm. L'adresse de retour doit être dans la liste
/// autorisée (pas de redirection ouverte).
pub async fn start(State(s): State<AppState>, AuthUser(p): AuthUser, Json(body): Json<StartIn>) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("lastfm_start:{}", p.id), 10, 60).await?;
    let key = s.cfg.lastfm_api_key.as_deref().ok_or(AppError::NotConfigured("LASTFM_API_KEY"))?;
    if !is_allowed_return_url(&body.return_to, &s.cfg.allowed_return_urls) {
        return Err(AppError::bad("Adresse de retour non autorisée."));
    }
    let url = url::Url::parse_with_params(AUTH_URL, [("api_key", key), ("cb", body.return_to.as_str())]).expect("URL Last.fm");
    Ok(Json(json!({ "auth_url": url.as_str() })))
}

#[derive(Deserialize)]
pub struct ConnectIn {
    pub token: String,
}

fn valid_token(t: &str) -> bool {
    (20..=64).contains(&t.len()) && t.bytes().all(|b| b.is_ascii_alphanumeric())
}

/// Échange le jeton de retour contre la clé de session, chiffrée et liée au compte.
pub async fn connect(State(s): State<AppState>, AuthUser(p): AuthUser, Json(body): Json<ConnectIn>) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("lastfm_connect:{}", p.id), 6, 60).await?;
    if !valid_token(&body.token) {
        return Err(LastfmError::TokenInvalid.into());
    }
    let vault = s.vault.as_ref().ok_or(AppError::NotConfigured("SECRETS_ENCRYPTION_KEY"))?;
    let api = client(&s)?;
    let mut params = BTreeMap::new();
    params.insert("token".to_string(), body.token.clone());
    let res = api.call("auth.getSession", params, false).await?;
    let name = res["session"]["name"].as_str().ok_or_else(|| AppError::Upstream("Réponse Last.fm inattendue.".into()))?;
    let key = res["session"]["key"].as_str().ok_or_else(|| AppError::Upstream("Réponse Last.fm inattendue.".into()))?;
    let sealed = vault.seal(key, &p.id.to_string());
    sqlx::query(
        "insert into public.connected_services (user_id, provider, external_username, secret_encrypted, connected_at, last_error)
         values ($1, 'lastfm', $2, $3, now(), null)
         on conflict (user_id, provider) do update
           set external_username = excluded.external_username, secret_encrypted = excluded.secret_encrypted,
               connected_at = now(), last_error = null",
    )
    .bind(p.id)
    .bind(name)
    .bind(sealed)
    .execute(&s.pool)
    .await?;
    Ok(Json(json!({ "connected": true, "username": name })))
}

pub async fn status(State(s): State<AppState>, AuthUser(p): AuthUser) -> Result<Json<Value>> {
    let row: Option<(Option<String>, Option<String>, Option<String>, bool)> = sqlx::query_as(
        "select external_username, last_error, last_sync_at::text, secret_encrypted is not null
         from public.connected_services where user_id = $1 and provider = 'lastfm'",
    )
    .bind(p.id)
    .fetch_optional(&s.pool)
    .await?;
    Ok(Json(match row {
        Some((username, last_error, last_sync_at, has_key)) => json!({
            "connected": has_key, "username": username, "last_error": last_error, "last_sync_at": last_sync_at }),
        None => json!({ "connected": false }),
    }))
}

/// Supprime la clé (et ce qui attendait d'être envoyé). Possible même sanctionné.
pub async fn disconnect(State(s): State<AppState>, AuthAny(p): AuthAny) -> Result<Json<Value>> {
    sqlx::query("delete from public.connected_services where user_id = $1 and provider = 'lastfm'").bind(p.id).execute(&s.pool).await?;
    sqlx::query("delete from private.scrobble_queue where user_id = $1").bind(p.id).execute(&s.pool).await?;
    Ok(Json(json!({ "connected": false })))
}

// ── File d'attente (appelée par le serveur musique) ──────────────────────

#[derive(Debug, Deserialize)]
pub struct EnqueueIn {
    pub user_id: Uuid,
    /// `scrobble` ou `now_playing`.
    pub kind: String,
    pub artist: String,
    pub track: String,
    #[serde(default)]
    pub album: Option<String>,
    #[serde(default)]
    pub duration: Option<u32>,
    /// Début de l'écoute, secondes Unix (scrobble).
    #[serde(default)]
    pub timestamp: Option<i64>,
}

fn clean(s: &str) -> Option<String> {
    let t = s.trim();
    (!t.is_empty() && t.chars().count() <= 256).then(|| t.to_string())
}

pub async fn enqueue(State(s): State<AppState>, _i: Internal, Json(b): Json<EnqueueIn>) -> Result<Json<Value>> {
    let artist = clean(&b.artist).ok_or_else(|| AppError::bad("artiste invalide"))?;
    let track = clean(&b.track).ok_or_else(|| AppError::bad("titre invalide"))?;
    let album = b.album.as_deref().and_then(clean);
    let now = chrono::Utc::now().timestamp();
    let mut payload = json!({ "artist": artist, "track": track });
    if let Some(a) = album {
        payload["album"] = json!(a);
    }
    if let Some(d) = b.duration.filter(|d| (1..=86_400).contains(d)) {
        payload["duration"] = json!(d);
    }
    match b.kind.as_str() {
        "scrobble" => {
            // Last.fm refuse les écoutes de plus de 14 jours ou futures.
            let ts = b.timestamp.ok_or_else(|| AppError::bad("timestamp manquant"))?;
            if ts < now - 14 * 86_400 || ts > now + 60 {
                return Err(AppError::bad("timestamp hors limites"));
            }
            payload["timestamp"] = json!(ts);
        }
        "now_playing" => {}
        _ => return Err(AppError::bad("type inconnu")),
    }
    // Rien n'est mis en file si le compte n'a pas connecté Last.fm ou a coupé le scrobbling.
    let wanted: Option<bool> = sqlx::query_scalar(
        "select coalesce(us.scrobbling_enabled, true) from public.connected_services cs
         left join public.user_settings us on us.user_id = cs.user_id
         where cs.user_id = $1 and cs.provider = 'lastfm' and cs.secret_encrypted is not null",
    )
    .bind(b.user_id)
    .fetch_optional(&s.pool)
    .await?;
    if wanted != Some(true) {
        return Ok(Json(json!({ "queued": false })));
    }
    if b.kind == "now_playing" {
        sqlx::query("delete from private.scrobble_queue where user_id = $1 and kind = 'now_playing'").bind(b.user_id).execute(&s.pool).await?;
    }
    sqlx::query("insert into private.scrobble_queue (user_id, kind, payload) values ($1, $2, $3)")
        .bind(b.user_id)
        .bind(&b.kind)
        .bind(payload)
        .execute(&s.pool)
        .await?;
    Ok(Json(json!({ "queued": true })))
}

/// Pseudo Last.fm d'un compte (l'import d'historique n'a besoin que de lui).
pub async fn internal_user(State(s): State<AppState>, _i: Internal, Path(uid): Path<Uuid>) -> Result<Json<Value>> {
    let name: Option<Option<String>> =
        sqlx::query_scalar("select external_username from public.connected_services where user_id = $1 and provider = 'lastfm' and secret_encrypted is not null")
            .bind(uid)
            .fetch_optional(&s.pool)
            .await?;
    Ok(Json(json!({ "username": name.flatten() })))
}

// ── Envoi ────────────────────────────────────────────────────────────────

#[derive(sqlx::FromRow)]
struct QueueRow {
    id: i64,
    user_id: Uuid,
    kind: String,
    payload: Value,
    attempts: i32,
}

fn backoff_seconds(attempts: i32) -> i64 {
    (30i64 << attempts.clamp(0, 7)).min(3600)
}

/// Un passage de la file. Renvoie le nombre de lignes traitées. Les verrous de
/// ligne (`skip locked`) permettent plusieurs instances sans doublon.
pub async fn tick(s: &AppState) -> Result<usize> {
    let Some(vault) = s.vault.as_ref() else { return Ok(0) };
    let Ok(api) = client(s) else { return Ok(0) };
    let mut tx = s.pool.begin().await?;
    let rows: Vec<QueueRow> = sqlx::query_as(
        "select id, user_id, kind, payload, attempts from private.scrobble_queue
         where next_attempt_at <= now() order by id limit 200 for update skip locked",
    )
    .fetch_all(&mut *tx)
    .await?;
    let mut by_user: BTreeMap<Uuid, Vec<QueueRow>> = BTreeMap::new();
    for r in rows {
        by_user.entry(r.user_id).or_default().push(r);
    }
    let mut handled = 0;
    for (user, rows) in by_user {
        let ids: Vec<i64> = rows.iter().map(|r| r.id).collect();
        handled += ids.len();
        let secret: Option<Option<String>> =
            sqlx::query_scalar("select secret_encrypted from public.connected_services where user_id = $1 and provider = 'lastfm'")
                .bind(user)
                .fetch_optional(&mut *tx)
                .await?;
        let Some(key) = secret.flatten().and_then(|sealed| vault.open(&sealed, &user.to_string()).ok()) else {
            // Plus connecté (ou clé illisible) : rien à envoyer.
            sqlx::query("delete from private.scrobble_queue where id = any($1)").bind(&ids).execute(&mut *tx).await?;
            continue;
        };
        let mut outcome: std::result::Result<(), LastfmError> = Ok(());
        // Écoutes par lots de 50 (limite de Last.fm), puis « en cours d'écoute ».
        let scrobbles: Vec<&QueueRow> = rows.iter().filter(|r| r.kind == "scrobble").collect();
        for chunk in scrobbles.chunks(50) {
            let mut params = BTreeMap::new();
            params.insert("sk".to_string(), key.clone());
            for (i, r) in chunk.iter().enumerate() {
                for (field, name) in [("artist", "artist"), ("track", "track"), ("album", "album"), ("duration", "duration"), ("timestamp", "timestamp")] {
                    if let Some(v) = r.payload.get(field) {
                        let text = v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string());
                        params.insert(format!("{name}[{i}]"), text);
                    }
                }
            }
            if let Err(e) = api.call("track.scrobble", params, true).await {
                outcome = Err(e);
                break;
            }
        }
        if outcome.is_ok() {
            if let Some(np) = rows.iter().rev().find(|r| r.kind == "now_playing") {
                let mut params = BTreeMap::new();
                params.insert("sk".to_string(), key.clone());
                for field in ["artist", "track", "album", "duration"] {
                    if let Some(v) = np.payload.get(field) {
                        params.insert(field.to_string(), v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string()));
                    }
                }
                outcome = api.call("track.updateNowPlaying", params, true).await.map(|_| ());
            }
        }
        match outcome {
            Ok(()) => {
                sqlx::query("delete from private.scrobble_queue where id = any($1)").bind(&ids).execute(&mut *tx).await?;
                sqlx::query("update public.connected_services set last_sync_at = now(), last_error = null where user_id = $1 and provider = 'lastfm'")
                    .bind(user)
                    .execute(&mut *tx)
                    .await?;
            }
            Err(LastfmError::SessionRevoked) => {
                // Clé révoquée : inutile de réessayer, on le dit à l'utilisateur.
                sqlx::query("delete from private.scrobble_queue where user_id = $1").bind(user).execute(&mut *tx).await?;
                sqlx::query("update public.connected_services set secret_encrypted = null, last_error = $2 where user_id = $1 and provider = 'lastfm'")
                    .bind(user)
                    .bind(LastfmError::SessionRevoked.to_string())
                    .execute(&mut *tx)
                    .await?;
            }
            Err(e) if e.retryable() => {
                let rate = e == LastfmError::RateLimited;
                for r in &rows {
                    if r.attempts >= 15 {
                        sqlx::query("delete from private.scrobble_queue where id = $1").bind(r.id).execute(&mut *tx).await?;
                    } else {
                        let wait = if rate { 600 } else { backoff_seconds(r.attempts) };
                        sqlx::query("update private.scrobble_queue set attempts = attempts + 1, next_attempt_at = now() + make_interval(secs => $2) where id = $1")
                            .bind(r.id)
                            .bind(wait as f64)
                            .execute(&mut *tx)
                            .await?;
                    }
                }
                sqlx::query("update public.connected_services set last_error = $2 where user_id = $1 and provider = 'lastfm'")
                    .bind(user)
                    .bind(e.to_string())
                    .execute(&mut *tx)
                    .await?;
            }
            Err(e) => {
                // Refus définitif (données invalides…) : on abandonne ces lignes.
                tracing::warn!(error = %e, "scrobble refusé par Last.fm");
                sqlx::query("delete from private.scrobble_queue where id = any($1)").bind(&ids).execute(&mut *tx).await?;
                sqlx::query("update public.connected_services set last_error = $2 where user_id = $1 and provider = 'lastfm'")
                    .bind(user)
                    .bind(e.to_string())
                    .execute(&mut *tx)
                    .await?;
            }
        }
    }
    tx.commit().await?;
    Ok(handled)
}

pub async fn run_worker(s: AppState) {
    loop {
        if let Err(e) = tick(&s).await {
            tracing::warn!(error = ?e.code(), "file de scrobbling");
        }
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_codes_map_to_clear_errors() {
        assert_eq!(LastfmError::from_code(14, ""), LastfmError::TokenNotAuthorized);
        assert_eq!(LastfmError::from_code(9, ""), LastfmError::SessionRevoked);
        assert_eq!(LastfmError::from_code(29, ""), LastfmError::RateLimited);
        assert!(LastfmError::from_code(16, "").retryable());
        assert!(!LastfmError::from_code(9, "").retryable());
        assert!(!LastfmError::from_code(6, "mauvais paramètre").retryable());
    }

    #[test]
    fn tokens_are_validated_before_any_network_call() {
        assert!(valid_token("abcdefghijklmnopqrstuvwxyz012345"));
        for bad in ["", "court", "avec espace dedans 123456789012", "a&b=c&d=eeeeeeeeeeeeeeeeeeeeeeee", &"x".repeat(80)] {
            assert!(!valid_token(bad), "{bad:?}");
        }
    }

    #[test]
    fn backoff_grows_and_is_capped() {
        assert_eq!(backoff_seconds(0), 30);
        assert_eq!(backoff_seconds(3), 240);
        assert_eq!(backoff_seconds(10), 3600);
    }
}
