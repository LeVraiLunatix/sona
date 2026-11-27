//! Connexion d'une application (Windows aujourd'hui, Rust demain) par le navigateur.
//!
//! 1. L'application tire un secret au hasard (`verifier`) et ouvre le site avec son
//!    empreinte (`challenge` = base64url(SHA-256(verifier))).
//! 2. La personne s'y connecte et confirme : `POST /app-link` rend un code.
//! 3. Le site rend la main à l'application (`sona://auth/callback?handoff=<code>`).
//! 4. `POST /app-link/exchange` avec le code ET le secret : l'application reçoit un
//!    `token_hash`, qu'elle échange contre sa propre session Supabase (`verifyOtp`).
//!
//! Aucun jeton de session ne passe dans une adresse ; un code intercepté ne sert à rien
//! sans le secret resté dans l'application.

use crate::auth::AuthUser;
use crate::error::{AppError, Result};
use crate::passkey::{client_key, magic_token_hash};
use crate::ratelimit;
use crate::state::AppState;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::Json;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rand::RngCore;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

const REFUSED: &str = "Cette demande de connexion a expiré : recommence depuis l'application.";

fn digest(v: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(v.as_bytes()))
}

/// Compte qui peut ouvrir une application : il lui faut une adresse (pas un invité).
async fn email_of(s: &AppState, user: Uuid) -> Result<String> {
    let email: Option<String> = sqlx::query_scalar("select email from auth.users where id = $1").bind(user).fetch_one(&s.pool).await?;
    email.filter(|e| !e.is_empty()).ok_or_else(|| AppError::bad("Crée d'abord ton compte : un invité ne peut pas connecter une application."))
}

#[derive(Deserialize)]
pub struct CreateIn {
    pub challenge: String,
}

pub async fn create(State(s): State<AppState>, AuthUser(p): AuthUser, Json(b): Json<CreateIn>) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("app_link:{}", p.id), 10, 600).await?;
    if URL_SAFE_NO_PAD.decode(&b.challenge).map(|d| d.len()) != Ok(32) {
        return Err(AppError::bad("Demande de connexion invalide."));
    }
    email_of(&s, p.id).await?;
    let mut raw = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut raw);
    let code = URL_SAFE_NO_PAD.encode(raw);
    sqlx::query("delete from private.app_links where expires_at < now()").execute(&s.pool).await?;
    sqlx::query("insert into private.app_links (code_hash, user_id, challenge) values ($1, $2, $3)")
        .bind(digest(&code))
        .bind(p.id)
        .bind(&b.challenge)
        .execute(&s.pool)
        .await?;
    Ok(Json(json!({ "code": code })))
}

#[derive(Deserialize)]
pub struct ExchangeIn {
    pub code: String,
    pub verifier: String,
}

pub async fn exchange(State(s): State<AppState>, headers: HeaderMap, Json(b): Json<ExchangeIn>) -> Result<Json<Value>> {
    ratelimit::check(&s.pool, &format!("app_link_exchange:{}", client_key(&headers)), 20, 60).await?;
    // Usage unique : le code est détruit dès qu'il est présenté, juste ou faux secret.
    let row: Option<(Uuid, String)> = sqlx::query_as("delete from private.app_links where code_hash = $1 and expires_at > now() returning user_id, challenge")
        .bind(digest(&b.code))
        .fetch_optional(&s.pool)
        .await?;
    let (user, challenge) = row.ok_or_else(|| AppError::bad(REFUSED))?;
    if digest(&b.verifier) != challenge {
        return Err(AppError::bad(REFUSED));
    }
    let profile = s.auth.profile(user).await.map_err(|_| AppError::bad(REFUSED))?;
    if let Some(e) = profile.sanction_error() {
        return Err(e);
    }
    let token_hash = magic_token_hash(&s, &email_of(&s, user).await?).await?;
    Ok(Json(json!({ "token_hash": token_hash, "type": "email" })))
}
