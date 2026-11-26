use crate::auth::AuthUser;
use crate::state::AppState;
use crate::{account, admin, alerts, hooks, internal, lastfm, passkey};
use axum::extract::State;
use axum::http::{header, HeaderName, HeaderValue, Method};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use serde_json::{json, Value};
use tower_http::cors::{AllowOrigin, CorsLayer};
use tower_http::limit::RequestBodyLimitLayer;

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// Qui suis-je, vu du serveur (rôle relu en base) : l'interface s'en sert pour
/// décider d'afficher l'entrée Admin ; les vraies protections restent côté serveur.
async fn me(AuthUser(p): AuthUser) -> Json<Value> {
    Json(json!({ "id": p.id, "username": p.username, "role": p.role, "status": p.status, "staff": p.is_staff(), "admin": p.is_admin() }))
}

pub fn router(state: AppState) -> Router {
    let origins: Vec<HeaderValue> = state.cfg.cors_origins.iter().filter_map(|o| o.parse().ok()).collect();
    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(origins))
        .allow_methods([Method::GET, Method::POST, Method::DELETE, Method::OPTIONS])
        .allow_headers([header::AUTHORIZATION, header::CONTENT_TYPE, HeaderName::from_static("x-client-info")])
        .max_age(std::time::Duration::from_secs(600));
    let _ = alerts::format_alert; // (alertes : worker séparé)

    Router::new()
        .route("/health", get(health))
        .route("/me", get(me))
        // Last.fm
        .route("/lastfm/start", post(lastfm::start))
        .route("/lastfm/connect", post(lastfm::connect))
        .route("/lastfm/status", get(lastfm::status))
        .route("/lastfm", delete(lastfm::disconnect))
        // Compte (RGPD)
        .route("/account/export", get(account::export))
        .route("/account", delete(account::delete))
        // Passkeys
        .route("/passkey/register/start", post(passkey::register_start))
        .route("/passkey/register/finish", post(passkey::register_finish))
        .route("/passkey/login/start", post(passkey::login_start))
        .route("/passkey/login/finish", post(passkey::login_finish))
        // Administration
        .route("/admin/sanction", post(admin::sanction))
        .route("/admin/lift", post(admin::lift))
        .route("/admin/reset-profile", post(admin::reset_profile))
        .route("/admin/role", post(admin::set_role))
        .route("/admin/revoke-sessions", post(admin::revoke_sessions))
        .route("/admin/ban-identifier", post(admin::ban_identifier))
        .route("/admin/forbidden-term", post(admin::forbidden_term))
        .route("/admin/report", post(admin::update_report))
        .route("/admin/appeal", post(admin::resolve_appeal))
        .route("/admin/delete-user", post(admin::delete_user))
        .route("/admin/content", post(admin::content))
        .route("/admin/session", post(admin::session_action))
        // Hook Supabase Auth
        .route("/hooks/before-user-created", post(hooks::before_user_created))
        // Serveur musique
        .route("/internal/verify", post(internal::verify))
        .route("/internal/relations", post(internal::relations))
        .route("/internal/friends/{uid}", get(internal::friends))
        .route("/internal/profiles", post(internal::profiles))
        .route("/internal/notify/session-invite", post(internal::notify_session_invite))
        .route("/internal/text-check", post(internal::text_check))
        .route("/internal/scrobble", post(lastfm::enqueue))
        .route("/internal/lastfm/{uid}", get(lastfm::internal_user))
        .layer(RequestBodyLimitLayer::new(64 * 1024))
        .layer(cors)
        .with_state(state)
}

#[allow(dead_code)]
async fn _unused(State(_): State<AppState>) {}
