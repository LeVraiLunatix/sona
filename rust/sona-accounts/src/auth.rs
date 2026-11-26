//! Authentification de chaque requête.
//!
//! 1. Le jeton Supabase est vérifié (signature, expiration, audience).
//! 2. Le statut du compte est relu en base (cache de quelques secondes) : un
//!    compte banni ou suspendu est refusé IMMÉDIATEMENT, même avec un jeton
//!    encore valable une heure. Le rôle vient toujours de la base, jamais du jeton.
//!
//! `Authenticator` est réutilisable tel quel par le serveur musique.

use crate::error::AppError;
use crate::jwt::JwtVerifier;
use crate::state::AppState;
use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use uuid::Uuid;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct Profile {
    pub id: Uuid,
    pub username: String,
    pub role: String,
    pub status: String,
    pub status_reason: Option<String>,
    pub status_until: Option<String>,
}

impl Profile {
    pub fn is_staff(&self) -> bool {
        self.status == "active" && (self.role == "moderator" || self.role == "admin")
    }
    pub fn is_admin(&self) -> bool {
        self.status == "active" && self.role == "admin"
    }
    pub fn sanction_error(&self) -> Option<AppError> {
        matches!(self.status.as_str(), "banned" | "suspended").then(|| AppError::Sanctioned {
            status: self.status.clone(),
            reason: self.status_reason.clone(),
            until: self.status_until.clone(),
        })
    }
}

pub struct Authenticator {
    pool: PgPool,
    jwt: Arc<JwtVerifier>,
    ttl: Duration,
    cache: Mutex<HashMap<Uuid, (Instant, Profile)>>,
}

impl Authenticator {
    pub fn new(pool: PgPool, jwt: Arc<JwtVerifier>, ttl: Duration) -> Self {
        Authenticator { pool, jwt, ttl, cache: Mutex::new(HashMap::new()) }
    }

    /// Oublie le statut en cache (appelé après une sanction décidée ici).
    pub fn invalidate(&self, user: Uuid) {
        self.cache.lock().unwrap().remove(&user);
    }

    pub async fn profile(&self, user: Uuid) -> Result<Profile, AppError> {
        if let Some((at, p)) = self.cache.lock().unwrap().get(&user) {
            if at.elapsed() < self.ttl {
                return Ok(p.clone());
            }
        }
        let p: Option<Profile> = sqlx::query_as(
            "select id, username, role::text as role, status::text as status, status_reason,
                    status_until::text as status_until
             from public.service_profiles(array[$1]::uuid[])",
        )
        .bind(user)
        .fetch_optional(&self.pool)
        .await?;
        let p = p.ok_or(AppError::Unauthorized)?;
        self.cache.lock().unwrap().insert(user, (Instant::now(), p.clone()));
        // « Vu récemment » (au plus une écriture toutes les 5 min, côté SQL).
        let pool = self.pool.clone();
        tokio::spawn(async move {
            let _ = sqlx::query("select public.service_touch($1)").bind(user).execute(&pool).await;
        });
        Ok(p)
    }

    /// Jeton valable ET compte existant ; ne regarde pas les sanctions
    /// (export, suppression, contestation restent possibles pour tous).
    pub async fn authenticate_any(&self, token: &str) -> Result<Profile, AppError> {
        let claims = self.jwt.verify(token).await?;
        let id = Uuid::parse_str(&claims.sub).map_err(|_| AppError::Unauthorized)?;
        self.profile(id).await
    }

    /// Cas général : refuse les comptes bannis ou suspendus.
    pub async fn authenticate(&self, token: &str) -> Result<Profile, AppError> {
        let p = self.authenticate_any(token).await?;
        match p.sanction_error() {
            Some(e) => Err(e),
            None => Ok(p),
        }
    }
}

fn bearer(parts: &Parts) -> Result<&str, AppError> {
    let h = parts.headers.get(axum::http::header::AUTHORIZATION).and_then(|v| v.to_str().ok()).ok_or(AppError::Unauthorized)?;
    let (scheme, token) = h.split_once(' ').ok_or(AppError::Unauthorized)?;
    if !scheme.eq_ignore_ascii_case("bearer") || token.trim().is_empty() {
        return Err(AppError::Unauthorized);
    }
    Ok(token.trim())
}

/// Compte connecté et en règle (actif ou en quarantaine).
pub struct AuthUser(pub Profile);
/// Compte connecté, quelles que soient ses sanctions.
pub struct AuthAny(pub Profile);
/// Modérateur ou admin, rôle relu en base.
pub struct Staff(pub Profile);
/// Admin, rôle relu en base.
pub struct AdminUser(pub Profile);

impl FromRequestParts<AppState> for AuthUser {
    type Rejection = AppError;
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        Ok(AuthUser(state.auth.authenticate(bearer(parts)?).await?))
    }
}

impl FromRequestParts<AppState> for AuthAny {
    type Rejection = AppError;
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        Ok(AuthAny(state.auth.authenticate_any(bearer(parts)?).await?))
    }
}

impl FromRequestParts<AppState> for Staff {
    type Rejection = AppError;
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        let p = state.auth.authenticate(bearer(parts)?).await?;
        if !p.is_staff() {
            return Err(AppError::Forbidden);
        }
        Ok(Staff(p))
    }
}

impl FromRequestParts<AppState> for AdminUser {
    type Rejection = AppError;
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        let p = state.auth.authenticate(bearer(parts)?).await?;
        if !p.is_admin() {
            return Err(AppError::Forbidden);
        }
        Ok(AdminUser(p))
    }
}

/// Appels de serveur à serveur (`/internal/*`) : en-tête `x-sona-internal`,
/// comparé en temps constant. Sans secret configuré, la route est fermée.
pub struct Internal;

impl FromRequestParts<AppState> for Internal {
    type Rejection = AppError;
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        use subtle::ConstantTimeEq;
        let expected = state.cfg.internal_secret.as_deref().ok_or(AppError::NotConfigured("INTERNAL_API_SECRET"))?;
        let got = parts.headers.get("x-sona-internal").and_then(|v| v.to_str().ok()).unwrap_or("");
        if got.as_bytes().ct_eq(expected.as_bytes()).unwrap_u8() == 1 {
            Ok(Internal)
        } else {
            Err(AppError::Forbidden)
        }
    }
}
