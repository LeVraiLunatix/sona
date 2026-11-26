//! Hook Supabase « avant la création d'un utilisateur » : seul endroit qui
//! connaît l'adresse IP de l'inscription. Refuse e-mails jetables, e-mails /
//! identifiants OAuth / IP bannis, et les créations en masse depuis une même IP.
//! La requête est authentifiée par signature (Standard Webhooks).

use crate::state::AppState;
use crate::webhook;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::{json, Value};

fn refuse(reason: &str) -> Response {
    let message = match reason {
        "disposable_email" => "Les adresses e-mail temporaires ne sont pas acceptées.",
        "ip_burst" => "Trop d'inscriptions depuis ta connexion. Réessaie plus tard.",
        _ => "Inscription impossible avec ces informations.",
    };
    (StatusCode::FORBIDDEN, Json(json!({ "error": { "http_code": 403, "message": message } }))).into_response()
}

pub async fn before_user_created(State(s): State<AppState>, headers: HeaderMap, body: Bytes) -> Response {
    let Some(secret) = s.cfg.hook_secret.as_deref() else {
        return (StatusCode::SERVICE_UNAVAILABLE, Json(json!({ "error": "hook non configuré" }))).into_response();
    };
    let h = |name: &str| headers.get(name).and_then(|v| v.to_str().ok()).unwrap_or("");
    let now = chrono::Utc::now().timestamp();
    if !webhook::verify(secret, h("webhook-id"), h("webhook-timestamp"), h("webhook-signature"), &body, now) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(payload) = serde_json::from_slice::<Value>(&body) else { return StatusCode::BAD_REQUEST.into_response() };
    let user = &payload["user"];
    let email = user["email"].as_str();
    let provider = user["app_metadata"]["provider"].as_str().unwrap_or("email");
    let subject = user["user_metadata"]["provider_id"].as_str().or_else(|| user["user_metadata"]["sub"].as_str());
    let ip = payload["metadata"]["ip_address"].as_str().and_then(|v| v.parse::<std::net::IpAddr>().ok()).map(|i| i.to_string());
    let verdict: std::result::Result<Option<String>, sqlx::Error> =
        sqlx::query_scalar("select public.signup_guard($1, $2, $3, $4::inet)").bind(email).bind(provider).bind(subject).bind(ip).fetch_one(&s.pool).await;
    match verdict {
        Ok(None) => Json(json!({})).into_response(),
        Ok(Some(reason)) => refuse(&reason),
        Err(e) => {
            // Si la base est indisponible on ne bloque pas toute inscription : le
            // déclencheur SQL sur auth.users reste le dernier rempart.
            tracing::error!(error = %e, "signup_guard");
            Json(json!({})).into_response()
        }
    }
}
