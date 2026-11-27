//! Passkeys (Face ID, Touch ID, Windows Hello) avec WebAuthn.
//!
//! Supabase Auth ne les fournit pas (à ma connaissance, non vérifié : la doc n'a
//! pas pu être consultée) : on les gère ici avec `webauthn-rs`.
//!  * enregistrement : compte connecté seulement ;
//!  * connexion : « découvrable » (aucun e-mail à saisir). Après vérification,
//!    on fabrique un lien magique côté serveur (API admin d'Auth) dont le client
//!    échange le `token_hash` contre une vraie session Supabase (`verifyOtp`).
//!  * l'état des défis est en base, valable 5 minutes, à usage unique.

use crate::auth::AuthUser;
use crate::error::{AppError, Result};
use crate::ratelimit;
use crate::state::AppState;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::Json;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;
use webauthn_rs::prelude::*;

fn webauthn(s: &AppState) -> Result<&Webauthn> {
    s.webauthn.as_deref().ok_or(AppError::NotConfigured("WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN"))
}

fn bad_passkey<E: std::fmt::Debug>(e: E) -> AppError {
    tracing::info!(error = ?e, "passkey refusée");
    AppError::bad("La clé d'accès n'a pas pu être vérifiée.")
}

/// Adresse qui sert aux limites anti-abus : la DERNIÈRE de `X-Forwarded-For`, ajoutée par le proxy
/// placé devant le service. Les précédentes sont écrites par l'appelant, qui les change à volonté.
pub(crate) fn client_key(h: &HeaderMap) -> String {
    h.get("x-forwarded-for").and_then(|v| v.to_str().ok()).and_then(|v| v.rsplit(',').next()).map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).unwrap_or_else(|| "inconnu".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn client_key_ignores_what_the_caller_wrote() {
        let mut h = HeaderMap::new();
        h.insert("x-forwarded-for", "1.2.3.4, 9.9.9.9".parse().unwrap());
        assert_eq!(client_key(&h), "9.9.9.9");
        assert_eq!(client_key(&HeaderMap::new()), "inconnu");
    }
}

async fn save_state(s: &AppState, user: Option<Uuid>, kind: &str, state: &impl serde::Serialize) -> Result<Uuid> {
    let json = serde_json::to_string(state).map_err(|e| AppError::Internal(e.to_string()))?;
    Ok(sqlx::query_scalar("insert into private.passkey_challenges (user_id, kind, challenge) values ($1, $2, $3) returning id")
        .bind(user)
        .bind(kind)
        .bind(json)
        .fetch_one(&s.pool)
        .await?)
}

/// Lit ET supprime l'état (usage unique) ; refuse un défi expiré ou d'un autre compte.
async fn take_state(s: &AppState, id: Uuid, kind: &str, user: Option<Uuid>) -> Result<String> {
    let row: Option<(String,)> = sqlx::query_as(
        "delete from private.passkey_challenges
         where id = $1 and kind = $2 and expires_at > now() and (user_id is not distinct from $3)
         returning challenge",
    )
    .bind(id)
    .bind(kind)
    .bind(user)
    .fetch_optional(&s.pool)
    .await?;
    row.map(|r| r.0).ok_or_else(|| AppError::bad("Défi expiré : recommence."))
}

pub async fn register_start(State(s): State<AppState>, AuthUser(p): AuthUser) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("passkey_reg:{}", p.id), 10, 3600).await?;
    let w = webauthn(&s)?;
    let existing: Vec<String> = sqlx::query_scalar("select credential_id from public.passkey_credentials where user_id = $1").bind(p.id).fetch_all(&s.pool).await?;
    if existing.len() >= 10 {
        return Err(AppError::bad("Tu as déjà 10 clés d'accès : supprime-en une d'abord."));
    }
    let exclude: Vec<CredentialID> = existing.iter().filter_map(|c| URL_SAFE_NO_PAD.decode(c).ok()).map(CredentialID::from).collect();
    let (options, state) = w.start_passkey_registration(p.id, &p.username, &p.username, Some(exclude)).map_err(bad_passkey)?;
    let id = save_state(&s, Some(p.id), "register", &state).await?;
    let mut options = serde_json::to_value(&options).map_err(|e| AppError::Internal(e.to_string()))?;
    // Connexion sans e-mail : la clé doit être « découvrable » (stockée sur l'appareil).
    // La bibliothèque la laisse « déconseillée » ; la vérification côté serveur n'en dépend pas.
    options["publicKey"]["authenticatorSelection"]["residentKey"] = json!("required");
    options["publicKey"]["authenticatorSelection"]["requireResidentKey"] = json!(true);
    Ok(Json(json!({ "challenge_id": id, "options": options })))
}

#[derive(Deserialize)]
pub struct RegisterFinishIn {
    pub challenge_id: Uuid,
    pub credential: RegisterPublicKeyCredential,
    pub device_name: Option<String>,
}

pub async fn register_finish(State(s): State<AppState>, AuthUser(p): AuthUser, Json(b): Json<RegisterFinishIn>) -> Result<Json<Value>> {
    let w = webauthn(&s)?;
    let state: PasskeyRegistration = serde_json::from_str(&take_state(&s, b.challenge_id, "register", Some(p.id)).await?).map_err(bad_passkey)?;
    let passkey = w.finish_passkey_registration(&b.credential, &state).map_err(bad_passkey)?;
    let cred_id = URL_SAFE_NO_PAD.encode(passkey.cred_id().as_ref());
    let device = b.device_name.as_deref().map(str::trim).filter(|d| !d.is_empty()).map(|d| d.chars().take(40).collect::<String>());
    sqlx::query("insert into public.passkey_credentials (user_id, credential_id, public_key, device_name) values ($1, $2, $3, $4)")
        .bind(p.id)
        .bind(cred_id)
        .bind(serde_json::to_string(&passkey).map_err(|e| AppError::Internal(e.to_string()))?)
        .bind(device)
        .execute(&s.pool)
        .await?;
    Ok(Json(json!({ "ok": true })))
}

pub async fn login_start(State(s): State<AppState>, headers: HeaderMap) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("passkey_login:{}", client_key(&headers)), 30, 60).await?;
    let w = webauthn(&s)?;
    let (options, state) = w.start_discoverable_authentication().map_err(bad_passkey)?;
    let id = save_state(&s, None, "login", &state).await?;
    Ok(Json(json!({ "challenge_id": id, "options": options })))
}

#[derive(Deserialize)]
pub struct LoginFinishIn {
    pub challenge_id: Uuid,
    pub credential: PublicKeyCredential,
}

pub async fn login_finish(State(s): State<AppState>, headers: HeaderMap, Json(b): Json<LoginFinishIn>) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("passkey_login_finish:{}", client_key(&headers)), 30, 60).await?;
    let w = webauthn(&s)?;
    let state: DiscoverableAuthentication = serde_json::from_str(&take_state(&s, b.challenge_id, "login", None).await?).map_err(bad_passkey)?;
    let (user_id, _cred) = w.identify_discoverable_authentication(&b.credential).map_err(bad_passkey)?;
    // Compte sanctionné : même écran de sanction que partout ailleurs, pas de session.
    let profile = s.auth.profile(user_id).await.map_err(|_| AppError::bad("La clé d'accès n'a pas pu être vérifiée."))?;
    if let Some(e) = profile.sanction_error() {
        return Err(e);
    }
    let rows: Vec<(Uuid, String)> = sqlx::query_as("select id, public_key from public.passkey_credentials where user_id = $1").bind(user_id).fetch_all(&s.pool).await?;
    let mut passkeys: Vec<(Uuid, Passkey)> = rows.into_iter().filter_map(|(id, pk)| serde_json::from_str::<Passkey>(&pk).ok().map(|p| (id, p))).collect();
    let keys: Vec<DiscoverableKey> = passkeys.iter().map(|(_, p)| DiscoverableKey::from(p)).collect();
    let result = w.finish_discoverable_authentication(&b.credential, state, &keys).map_err(bad_passkey)?;
    // Compteur de signatures : détecte un clonage de clé.
    for (id, pk) in passkeys.iter_mut() {
        if pk.update_credential(&result).is_some() {
            sqlx::query("update public.passkey_credentials set public_key = $2, last_used_at = now() where id = $1")
                .bind(*id)
                .bind(serde_json::to_string(&pk).map_err(|e| AppError::Internal(e.to_string()))?)
                .execute(&s.pool)
                .await?;
        }
    }
    let email: Option<String> = sqlx::query_scalar("select email from auth.users where id = $1").bind(user_id).fetch_one(&s.pool).await?;
    let email = email.ok_or_else(|| AppError::bad("Ce compte n'a pas d'adresse e-mail : connecte-toi autrement."))?;
    let token_hash = magic_token_hash(&s, &email).await?;
    Ok(Json(json!({ "email": email, "token_hash": token_hash, "type": "email" })))
}

/// Lien magique fabriqué côté serveur (API admin d'Auth) : le client en tire une session.
pub(crate) async fn magic_token_hash(s: &AppState, email: &str) -> Result<String> {
    let key = s.cfg.supabase_service_key.as_deref().ok_or(AppError::NotConfigured("SUPABASE_SERVICE_ROLE_KEY"))?;
    let resp = s
        .http
        .post(format!("{}/auth/v1/admin/generate_link", s.cfg.supabase_url))
        .header("apikey", key)
        .bearer_auth(key)
        .json(&json!({ "type": "magiclink", "email": email }))
        .send()
        .await?;
    if !resp.status().is_success() {
        return Err(AppError::Upstream("Impossible d'ouvrir la session pour l'instant.".into()));
    }
    let v: Value = resp.json().await?;
    v["hashed_token"].as_str().map(str::to_string).ok_or_else(|| AppError::Upstream("Réponse d'Auth inattendue.".into()))
}
