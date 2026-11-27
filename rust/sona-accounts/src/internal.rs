//! Routes de serveur à serveur pour le serveur musique (en-tête `x-sona-internal`).
//! Il n'a pas à savoir lire la base Supabase : il pose des questions ici.

use crate::auth::Internal;
use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::{Path, State};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

#[derive(Deserialize)]
pub struct VerifyIn {
    pub token: String,
}

/// Valide un jeton d'accès (utile à un serveur qui n'utilise pas la crate) :
/// renvoie l'identité ET le statut à l'instant T. Refuse bannis et suspendus.
pub async fn verify(State(s): State<AppState>, _i: Internal, Json(b): Json<VerifyIn>) -> Result<Json<Value>> {
    let p = s.auth.authenticate(&b.token).await?;
    Ok(Json(json!({ "user_id": p.id, "username": p.username, "role": p.role, "status": p.status })))
}

#[derive(Deserialize)]
pub struct RelationsIn {
    pub viewer: Uuid,
    pub others: Vec<Uuid>,
}

/// Pour chaque compte : ami ? bloqué ? visible ? présence / historique /
/// statistiques / playlists accessibles à `viewer` ? (même règle que le SQL).
pub async fn relations(State(s): State<AppState>, _i: Internal, Json(b): Json<RelationsIn>) -> Result<Json<Value>> {
    if b.others.len() > 500 {
        return Err(AppError::bad("Trop de comptes (500 maximum)."));
    }
    let v: Value = sqlx::query_scalar("select public.batch_relations($1, $2)").bind(b.viewer).bind(&b.others).fetch_one(&s.pool).await?;
    Ok(Json(v))
}

pub async fn friends(State(s): State<AppState>, _i: Internal, Path(uid): Path<Uuid>) -> Result<Json<Value>> {
    let ids: Vec<Uuid> = sqlx::query_scalar("select public.service_friend_ids($1)").bind(uid).fetch_one(&s.pool).await?;
    Ok(Json(json!({ "friends": ids })))
}

#[derive(Deserialize)]
pub struct ProfilesIn {
    pub ids: Vec<Uuid>,
}

pub async fn profiles(State(s): State<AppState>, _i: Internal, Json(b): Json<ProfilesIn>) -> Result<Json<Value>> {
    if b.ids.len() > 500 {
        return Err(AppError::bad("Trop de comptes (500 maximum)."));
    }
    let rows: Vec<(Uuid, String, Option<String>, Option<String>, String)> = sqlx::query_as(
        "select id, username, display_name, avatar_url, status::text from public.service_profiles($1)",
    )
    .bind(&b.ids)
    .fetch_all(&s.pool)
    .await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, username, display_name, avatar_url, status)| json!({ "id": id, "username": username, "display_name": display_name, "avatar_url": avatar_url, "status": status }))
        .collect();
    Ok(Json(json!({ "profiles": out })))
}

#[derive(Deserialize)]
pub struct NotifyIn {
    pub user_id: Uuid,
    pub payload: Value,
}

/// Invitation à une session d'écoute (seul type de notification que le serveur musique peut créer).
pub async fn notify_session_invite(State(s): State<AppState>, _i: Internal, Json(b): Json<NotifyIn>) -> Result<Json<Value>> {
    sqlx::query("select public.service_notify($1, 'session_invite', $2)").bind(b.user_id).bind(b.payload).execute(&s.pool).await?;
    Ok(Json(json!({ "ok": true })))
}

#[derive(Deserialize)]
pub struct TextIn {
    pub text: String,
}

/// Filtre de mots (chat de session, messages) : vrai si le texte contient un terme interdit.
pub async fn text_check(State(s): State<AppState>, _i: Internal, Json(b): Json<TextIn>) -> Result<Json<Value>> {
    if b.text.len() > 4000 {
        return Err(AppError::bad("Texte trop long."));
    }
    let offensive: bool = sqlx::query_scalar("select private.text_has_offensive($1)").bind(&b.text).fetch_one(&s.pool).await?;
    Ok(Json(json!({ "offensive": offensive })))
}
