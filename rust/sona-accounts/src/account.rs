//! Droits RGPD de l'utilisateur : export de ses données, suppression de son
//! compte. Possibles quelles que soient les sanctions (même après un
//! avertissement, une suspension ou un ban).

use crate::auth::AuthAny;
use crate::error::{AppError, Result};
use crate::music;
use crate::ratelimit;
use crate::state::AppState;
use axum::extract::State;
use axum::http::{header, HeaderValue};
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};

pub const DELETE_PHRASE: &str = "SUPPRIMER MON COMPTE";

/// Toutes les données : compte (Postgres) + musique (serveur musique, si branché).
pub async fn export(State(s): State<AppState>, AuthAny(p): AuthAny) -> Result<Response> {
    ratelimit::check(&s.pool, &format!("export:{}", p.id), 5, 3600).await?;
    let account: Value = sqlx::query_scalar("select public.service_export($1)").bind(p.id).fetch_one(&s.pool).await?;
    let music_data = if music::configured(&s) {
        // Un export incomplet vaut mieux qu'aucun, mais on le dit.
        match music::call(&s, reqwest::Method::GET, &format!("/internal/users/{}/export", p.id), None).await {
            Ok(v) => v,
            Err(_) => json!({ "error": "Les données musicales n'ont pas pu être récupérées : réessaie plus tard." }),
        }
    } else {
        Value::Null
    };
    let body = serde_json::to_vec_pretty(&json!({ "account": account, "music": music_data })).map_err(|e| AppError::Internal(e.to_string()))?;
    let mut resp = body.into_response();
    resp.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json; charset=utf-8"));
    resp.headers_mut().insert(header::CONTENT_DISPOSITION, HeaderValue::from_static("attachment; filename=\"sona-mes-donnees.json\""));
    resp.headers_mut().insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    Ok(resp)
}

#[derive(Deserialize)]
pub struct DeleteIn {
    pub confirm: String,
}

pub async fn delete(State(s): State<AppState>, AuthAny(p): AuthAny, Json(b): Json<DeleteIn>) -> Result<Json<Value>> {
    if b.confirm.trim() != DELETE_PHRASE {
        return Err(AppError::bad(format!("Pour confirmer, écris exactement : {DELETE_PHRASE}")));
    }
    ratelimit::check(&s.pool, &format!("delete_account:{}", p.id), 3, 3600).await?;
    // Données musicales d'abord (voir admin::delete_user).
    if music::configured(&s) {
        music::call(&s, reqwest::Method::DELETE, &format!("/internal/users/{}", p.id), None).await?;
    }
    sqlx::query("select public.log_account_deletion($1, $1, 'suppression demandée par la personne concernée')").bind(p.id).execute(&s.pool).await?;
    sqlx::query("delete from auth.users where id = $1").bind(p.id).execute(&s.pool).await?;
    s.auth.invalidate(p.id);
    Ok(Json(json!({ "deleted": true })))
}
