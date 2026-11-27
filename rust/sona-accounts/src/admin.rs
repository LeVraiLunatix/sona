//! Administration et modération. Chaque route exige un compte de l'équipe
//! (`Staff` / `AdminUser`, rôle relu en base à chaque appel) ET les fonctions
//! SQL revérifient le rôle, la hiérarchie, le motif et les durées : cacher un
//! bouton dans l'interface ne protège de rien, et un bug ici ne suffit pas non
//! plus à contourner les règles.

use crate::auth::{AdminUser, Staff};
use crate::error::{AppError, Result};
use crate::music;
use crate::ratelimit;
use crate::state::AppState;
use axum::extract::State;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

/// Fin de ban « définitif » pour le champ `banned_until` d'Auth.
const FOREVER: &str = "2999-12-31T00:00:00Z";

async fn throttle(s: &AppState, actor: Uuid) -> Result<()> {
    ratelimit::check(&s.pool, &format!("admin:{actor}"), 120, 60).await
}

#[derive(Deserialize)]
pub struct SanctionIn {
    pub target: Uuid,
    /// warning | suspension | ban | quarantine
    pub kind: String,
    pub reason: String,
    pub duration_seconds: Option<i64>,
    pub report_id: Option<Uuid>,
}

pub async fn sanction(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<SanctionIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if !matches!(b.kind.as_str(), "warning" | "suspension" | "ban" | "quarantine") {
        return Err(AppError::bad("Type de sanction inconnu."));
    }
    let result: Value = sqlx::query_scalar("select public.admin_sanction($1, $2, $3, $4, make_interval(secs => $5), $6)")
        .bind(a.id)
        .bind(b.target)
        .bind(&b.kind)
        .bind(&b.reason)
        .bind(b.duration_seconds.map(|d| d as f64))
        .bind(b.report_id)
        .fetch_one(&s.pool)
        .await?;
    // Auth refuse aussi le renouvellement du jeton et la connexion.
    match b.kind.as_str() {
        "ban" => {
            sqlx::query("update auth.users set banned_until = $2::timestamptz where id = $1").bind(b.target).bind(FOREVER).execute(&s.pool).await?;
        }
        "suspension" => {
            sqlx::query("update auth.users set banned_until = (select status_until from public.profiles where id = $1) where id = $1")
                .bind(b.target)
                .execute(&s.pool)
                .await?;
        }
        _ => {}
    }
    s.auth.invalidate(b.target);
    Ok(Json(result))
}

#[derive(Deserialize)]
pub struct LiftIn {
    pub target: Uuid,
    pub reason: String,
}

pub async fn lift(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<LiftIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    let result: Value =
        sqlx::query_scalar("select public.admin_lift($1, $2, $3)").bind(a.id).bind(b.target).bind(&b.reason).fetch_one(&s.pool).await?;
    sqlx::query("update auth.users set banned_until = null where id = $1").bind(b.target).execute(&s.pool).await?;
    s.auth.invalidate(b.target);
    Ok(Json(result))
}

#[derive(Deserialize)]
pub struct ResetIn {
    pub target: Uuid,
    pub fields: Vec<String>,
    #[serde(default)]
    pub force: bool,
    pub reason: String,
}

pub async fn reset_profile(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<ResetIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    sqlx::query("select public.admin_reset_profile($1, $2, $3, $4, $5)")
        .bind(a.id)
        .bind(b.target)
        .bind(&b.fields)
        .bind(b.force)
        .bind(&b.reason)
        .execute(&s.pool)
        .await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct RoleIn {
    pub target: Uuid,
    pub role: String,
    pub reason: String,
}

pub async fn set_role(State(s): State<AppState>, AdminUser(a): AdminUser, Json(b): Json<RoleIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if !matches!(b.role.as_str(), "user" | "moderator" | "admin") {
        return Err(AppError::bad("Rôle inconnu."));
    }
    sqlx::query("select public.admin_set_role($1, $2, $3, $4)").bind(a.id).bind(b.target).bind(&b.role).bind(&b.reason).execute(&s.pool).await?;
    s.auth.invalidate(b.target);
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct RevokeIn {
    pub target: Uuid,
    pub reason: String,
}

/// Déconnecte l'utilisateur de tous ses appareils.
pub async fn revoke_sessions(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<RevokeIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    sqlx::query("select public.admin_revoke_sessions($1, $2, $3)").bind(a.id).bind(b.target).bind(&b.reason).execute(&s.pool).await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct BanIdentifierIn {
    /// email | email_domain | ip
    pub kind: String,
    pub value: String,
    pub reason: String,
    pub duration_seconds: Option<i64>,
}

pub async fn ban_identifier(State(s): State<AppState>, AdminUser(a): AdminUser, Json(b): Json<BanIdentifierIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if b.value.len() > 200 {
        return Err(AppError::bad("Valeur trop longue."));
    }
    sqlx::query("select public.admin_ban_identifier($1, $2, $3, $4, make_interval(secs => $5))")
        .bind(a.id)
        .bind(&b.kind)
        .bind(&b.value)
        .bind(&b.reason)
        .bind(b.duration_seconds.map(|d| d as f64))
        .execute(&s.pool)
        .await
        .map_err(|e| match &e {
            // Adresse IP / plage mal formée.
            sqlx::Error::Database(d) if d.code().as_deref() == Some("22P02") => AppError::bad("Adresse ou plage invalide."),
            _ => e.into(),
        })?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct TermIn {
    pub term: String,
    /// reserved | offensive
    pub kind: String,
}

pub async fn forbidden_term(State(s): State<AppState>, AdminUser(a): AdminUser, Json(b): Json<TermIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if !matches!(b.kind.as_str(), "reserved" | "offensive") || b.term.trim().len() < 3 || b.term.len() > 40 {
        return Err(AppError::bad("Terme invalide (3 à 40 caractères)."));
    }
    sqlx::query("select public.admin_add_forbidden_term($1, $2, $3)").bind(a.id).bind(&b.term).bind(&b.kind).execute(&s.pool).await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct ReportIn {
    pub report: Uuid,
    /// open | in_progress | resolved | dismissed
    pub status: String,
    pub assign_to: Option<Uuid>,
    pub resolution: Option<String>,
    pub note: Option<String>,
}

pub async fn update_report(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<ReportIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    sqlx::query("select public.staff_update_report($1, $2, $3, $4, $5, $6)")
        .bind(a.id)
        .bind(b.report)
        .bind(&b.status)
        .bind(b.assign_to)
        .bind(b.resolution.as_deref())
        .bind(b.note.as_deref())
        .execute(&s.pool)
        .await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct AppealIn {
    pub appeal: Uuid,
    pub accept: bool,
    pub response: String,
}

pub async fn resolve_appeal(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<AppealIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    let target: Option<Uuid> = sqlx::query_scalar("select user_id from public.appeals where id = $1").bind(b.appeal).fetch_optional(&s.pool).await?;
    sqlx::query("select public.staff_resolve_appeal($1, $2, $3, $4)").bind(a.id).bind(b.appeal).bind(b.accept).bind(&b.response).execute(&s.pool).await?;
    if let (true, Some(t)) = (b.accept, target) {
        sqlx::query("update auth.users set banned_until = null where id = $1").bind(t).execute(&s.pool).await?;
        s.auth.invalidate(t);
    }
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct DeleteUserIn {
    pub target: Uuid,
    pub reason: String,
}

/// Supprime le compte et TOUTES ses données (réservé aux admins). Les données
/// musicales sont supprimées d'abord : si le serveur musique échoue, le compte
/// reste et l'admin peut réessayer (pas de données orphelines).
pub async fn delete_user(State(s): State<AppState>, AdminUser(a): AdminUser, Json(b): Json<DeleteUserIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    // Sa propre suppression passe par DELETE /account (avec confirmation).
    if b.target == a.id {
        return Err(AppError::Forbidden);
    }
    // La base vérifie rôle, hiérarchie et motif, et journalise.
    sqlx::query("select public.log_account_deletion($1, $2, $3)").bind(a.id).bind(b.target).bind(&b.reason).execute(&s.pool).await?;
    if music::configured(&s) {
        music::call(&s, reqwest::Method::DELETE, &format!("/internal/users/{}", b.target), None).await?;
    }
    sqlx::query("delete from auth.users where id = $1").bind(b.target).execute(&s.pool).await?;
    s.auth.invalidate(b.target);
    Ok(Json(json!({ "deleted": true, "music_data_removed": music::configured(&s) })))
}

#[derive(Deserialize)]
pub struct ContentIn {
    /// hide | delete
    pub action: String,
    /// playlist
    pub kind: String,
    pub owner: Uuid,
    #[serde(rename = "ref")]
    pub reference: String,
    pub reason: String,
}

/// Masque ou supprime une playlist publique (les playlists vivent dans le serveur musique).
pub async fn content(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<ContentIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if b.kind != "playlist" || !matches!(b.action.as_str(), "hide" | "delete") {
        return Err(AppError::bad("Contenu ou action inconnus."));
    }
    if b.reference.is_empty() || b.reference.len() > 64 || !b.reference.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_') {
        return Err(AppError::bad("Référence invalide."));
    }
    // Journalisation d'abord : elle exige le motif et vérifie le rôle.
    sqlx::query("select public.admin_audit($1, $2, $3, $4, $5, $6, $7)")
        .bind(a.id)
        .bind(format!("content.{}", b.action))
        .bind(b.owner)
        .bind(&b.kind)
        .bind(&b.reference)
        .bind(&b.reason)
        .bind(json!({}))
        .execute(&s.pool)
        .await?;
    music::call(&s, reqwest::Method::POST, &format!("/internal/content/{}/{}/{}", b.kind, b.reference, b.action), Some(json!({ "owner": b.owner }))).await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct SessionActionIn {
    pub code: String,
    /// close | kick | delete_message
    pub action: String,
    pub user: Option<Uuid>,
    pub message_id: Option<String>,
    pub reason: String,
}

/// Ferme une session d'écoute, en expulse quelqu'un ou supprime un message.
pub async fn session_action(State(s): State<AppState>, Staff(a): Staff, Json(b): Json<SessionActionIn>) -> Result<Json<Value>> {
    throttle(&s, a.id).await?;
    if !matches!(b.action.as_str(), "close" | "kick" | "delete_message") || b.code.len() > 16 || !b.code.bytes().all(|c| c.is_ascii_alphanumeric()) {
        return Err(AppError::bad("Action ou code de session invalide."));
    }
    sqlx::query("select public.admin_audit($1, $2, $3, 'session', $4, $5, '{}'::jsonb)")
        .bind(a.id)
        .bind(format!("session.{}", b.action))
        .bind(b.user)
        .bind(&b.code)
        .bind(&b.reason)
        .execute(&s.pool)
        .await?;
    music::call(&s, reqwest::Method::POST, &format!("/internal/sessions/{}/{}", b.code, b.action), Some(json!({ "user": b.user, "message_id": b.message_id }))).await?;
    Ok(Json(json!({ "ok": true })))
}
