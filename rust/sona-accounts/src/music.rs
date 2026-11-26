//! Appels vers le serveur musique (adresse interne, secret partagé) : export,
//! suppression des données d'un compte, masquage de contenu, sessions d'écoute.

use crate::error::{AppError, Result};
use crate::state::AppState;
use serde_json::Value;

pub fn configured(s: &AppState) -> bool {
    s.cfg.music_internal_url.is_some() && s.cfg.internal_secret.is_some()
}

pub async fn call(s: &AppState, method: reqwest::Method, path: &str, body: Option<Value>) -> Result<Value> {
    let base = s.cfg.music_internal_url.as_deref().ok_or(AppError::NotConfigured("MUSIC_INTERNAL_URL"))?;
    let secret = s.cfg.internal_secret.as_deref().ok_or(AppError::NotConfigured("INTERNAL_API_SECRET"))?;
    let mut req = s.http.request(method, format!("{base}{path}")).header("x-sona-internal", secret);
    if let Some(b) = body {
        req = req.json(&b);
    }
    let resp = req.send().await?;
    let status = resp.status();
    if !status.is_success() {
        return Err(AppError::Upstream(format!("Le serveur musique a répondu {status}.")));
    }
    if status == reqwest::StatusCode::NO_CONTENT {
        return Ok(Value::Null);
    }
    Ok(resp.json().await.unwrap_or(Value::Null))
}
