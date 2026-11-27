//! Erreurs de l'API : toujours du JSON `{ "error": "<code>", "message": "<français>" }`,
//! sans jamais renvoyer le détail d'une erreur interne (base, réseau…).

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("connexion requise")]
    Unauthorized,
    #[error("accès refusé")]
    Forbidden,
    /// Compte suspendu ou banni : l'app affiche l'écran de sanction.
    #[error("compte sanctionné")]
    Sanctioned { status: String, reason: Option<String>, until: Option<String> },
    #[error("{0}")]
    BadRequest(String),
    #[error("introuvable")]
    NotFound,
    #[error("trop de requêtes")]
    RateLimited,
    #[error("service non configuré : {0}")]
    NotConfigured(&'static str),
    #[error("{0}")]
    Upstream(String),
    #[error("erreur interne")]
    Internal(String),
}

impl AppError {
    pub fn bad(msg: impl Into<String>) -> Self {
        AppError::BadRequest(msg.into())
    }
    pub fn code(&self) -> &'static str {
        match self {
            AppError::Unauthorized => "unauthorized",
            AppError::Forbidden => "forbidden",
            AppError::Sanctioned { .. } => "sanctioned",
            AppError::BadRequest(_) => "bad_request",
            AppError::NotFound => "not_found",
            AppError::RateLimited => "rate_limited",
            AppError::NotConfigured(_) => "not_configured",
            AppError::Upstream(_) => "upstream",
            AppError::Internal(_) => "internal",
        }
    }
    pub fn status(&self) -> StatusCode {
        match self {
            AppError::Unauthorized => StatusCode::UNAUTHORIZED,
            AppError::Forbidden | AppError::Sanctioned { .. } => StatusCode::FORBIDDEN,
            AppError::BadRequest(_) => StatusCode::BAD_REQUEST,
            AppError::NotFound => StatusCode::NOT_FOUND,
            AppError::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            AppError::NotConfigured(_) => StatusCode::SERVICE_UNAVAILABLE,
            AppError::Upstream(_) => StatusCode::BAD_GATEWAY,
            AppError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let message = match &self {
            AppError::Unauthorized => "Connexion requise.".to_string(),
            AppError::Forbidden => "Action réservée à l'équipe de Sona.".to_string(),
            AppError::Sanctioned { status, .. } => match status.as_str() {
                "banned" => "Ton compte est banni.".to_string(),
                _ => "Ton compte est suspendu.".to_string(),
            },
            AppError::BadRequest(m) | AppError::Upstream(m) => m.clone(),
            AppError::NotFound => "Introuvable.".to_string(),
            AppError::RateLimited => "Trop de requêtes, réessaie dans un moment.".to_string(),
            AppError::NotConfigured(what) => format!("Fonction non configurée sur le serveur ({what})."),
            AppError::Internal(detail) => {
                // Le détail reste dans les logs, jamais dans la réponse.
                tracing::error!(detail = %detail, "erreur interne");
                "Erreur interne, réessaie plus tard.".to_string()
            }
        };
        let mut body = json!({ "error": self.code(), "message": message });
        if let AppError::Sanctioned { status, reason, until } = &self {
            body["status"] = json!(status);
            body["reason"] = json!(reason);
            body["until"] = json!(until);
        }
        (self.status(), Json(body)).into_response()
    }
}

impl From<sqlx::Error> for AppError {
    fn from(e: sqlx::Error) -> Self {
        // Les fonctions SQL lèvent des codes lisibles : on les traduit.
        if let sqlx::Error::Database(db) = &e {
            let msg = db.message();
            match (db.code().as_deref(), msg) {
                (Some("42501"), _) => return AppError::Forbidden,
                (Some("P0001"), "rate_limited") => return AppError::RateLimited,
                (Some("P0002"), _) => return AppError::NotFound,
                (Some("22023"), m) | (Some("22P02"), m) | (Some("23514"), m) => {
                    return AppError::BadRequest(translate_db_message(m))
                }
                _ => {}
            }
        }
        AppError::Internal(e.to_string())
    }
}

fn translate_db_message(m: &str) -> String {
    match m {
        "reason_required" => "Un motif est obligatoire (3 caractères minimum).".into(),
        "duration_required" => "Une durée est obligatoire pour une suspension.".into(),
        "unknown_field" | "unknown_kind" | "bad_status" => "Valeur inconnue.".into(),
        m if m.starts_with("username_") => "Pseudo refusé.".into(),
        _ => "Requête invalide.".into(),
    }
}

impl From<reqwest::Error> for AppError {
    fn from(e: reqwest::Error) -> Self {
        // L'URL peut contenir un secret (clé d'API en paramètre) : on ne la garde pas.
        AppError::Upstream(format!("Service distant injoignable ({}).", e.without_url()))
    }
}

pub type Result<T> = std::result::Result<T, AppError>;
