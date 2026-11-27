use sona_accounts::config::Config;
use sona_accounts::state::AppState;
use sona_accounts::{alerts, lastfm, routes};
use sqlx::postgres::PgPoolOptions;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() {
    // Journaux : jamais de jeton, d'e-mail ni de corps de requête (voir error.rs).
    tracing_subscriber::fmt().with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into())).init();
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Configuration invalide : {e}");
            std::process::exit(2);
        }
    };
    let pool = PgPoolOptions::new().max_connections(10).connect(&cfg.database_url).await.expect("connexion à la base");
    let bind = cfg.bind.clone();
    let state = AppState::new(cfg, pool.clone());
    if state.vault.is_none() {
        tracing::warn!("SECRETS_ENCRYPTION_KEY absent ou invalide : Last.fm désactivé");
    }
    tokio::spawn(lastfm::run_worker(state.clone()));
    tokio::spawn(alerts::run_worker(state.clone()));
    // Rétention et invités inactifs : une fois par heure.
    tokio::spawn(sona_accounts::maintenance::run_daily(state.clone()));
    let listener = tokio::net::TcpListener::bind(&bind).await.expect("port d'écoute");
    tracing::info!("sona-accounts à l'écoute sur {bind}");
    axum::serve(listener, routes::router(state)).with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    }).await.expect("serveur");
}
