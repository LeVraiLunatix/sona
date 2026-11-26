//! Tâches de fond : rétention des données (RGPD) et suppression des invités inactifs.

use crate::error::Result;
use crate::music;
use crate::state::AppState;
use uuid::Uuid;

/// Supprime les comptes invités (connexion anonyme) inactifs depuis `days` jours,
/// données musicales comprises (d'abord : en cas d'échec le compte reste et on
/// réessaie plus tard). Renvoie le nombre de comptes supprimés.
pub async fn purge_guests(s: &AppState, days: i32) -> Result<usize> {
    let ids: Vec<Uuid> = sqlx::query_scalar("select public.service_expired_guests($1)").bind(days).fetch_one(&s.pool).await?;
    let mut deleted = 0;
    for id in ids {
        if music::configured(s) && music::call(s, reqwest::Method::DELETE, &format!("/internal/users/{id}"), None).await.is_err() {
            tracing::warn!("suppression d'un invité reportée : le serveur musique n'a pas répondu");
            continue;
        }
        sqlx::query("delete from auth.users where id = $1 and is_anonymous").bind(id).execute(&s.pool).await?;
        s.auth.invalidate(id);
        deleted += 1;
    }
    Ok(deleted)
}

/// Un passage : rétention, détection d'un pic d'inscriptions, invités inactifs.
pub async fn tick(s: &AppState) {
    if let Err(e) = sqlx::query("select public.purge_expired()").execute(&s.pool).await {
        tracing::warn!(error = %e, "purge");
    }
    // Pic anormal d'inscriptions (30 par heure ou plus) : une alerte par heure au plus.
    if let Err(e) = sqlx::query("select private.detect_signup_spike()").execute(&s.pool).await {
        tracing::warn!(error = %e, "détection de pic d'inscriptions");
    }
    match purge_guests(s, 30).await {
        Ok(n) if n > 0 => tracing::info!(deleted = n, "invités inactifs supprimés"),
        Ok(_) => {}
        Err(e) => tracing::warn!(error = ?e.code(), "purge des invités"),
    }
}

pub async fn run_daily(s: AppState) {
    loop {
        tick(&s).await;
        tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
    }
}
