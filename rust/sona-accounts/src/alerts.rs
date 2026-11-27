//! Alertes pour l'équipe : nouveau signalement, nouvelle contestation,
//! quarantaine automatique, pic d'inscriptions. Envoyées sur un webhook Discord
//! (ALERTS_DISCORD_WEBHOOK). Les messages ne contiennent ni e-mail ni texte
//! écrit par un utilisateur : seulement des identifiants et des compteurs.

use crate::state::AppState;
use serde_json::{json, Value};

pub fn format_alert(kind: &str, payload: &Value) -> String {
    match kind {
        "new_report" => format!(
            "🚩 **Nouveau signalement** ({}, motif : {}). À traiter dans /admin.",
            payload["target_type"].as_str().unwrap_or("?"),
            payload["reason"].as_str().unwrap_or("?")
        ),
        "new_appeal" => "📨 **Nouvelle contestation** d'une sanction. À traiter dans /admin.".to_string(),
        "auto_quarantine" => format!(
            "🛑 **Quarantaine automatique** : un compte a reçu {} signalements en 7 jours. Il attend ta décision dans /admin.",
            payload["reports"].as_i64().unwrap_or(0)
        ),
        "signup_spike" => format!(
            "📈 **Pic d'inscriptions** : {} comptes créés en une heure.",
            payload["signups_last_hour"].as_i64().unwrap_or(0)
        ),
        "signup_burst" => "⚠️ **Inscriptions en rafale** depuis une même adresse IP (bloquées automatiquement).".to_string(),
        other => format!("ℹ️ Alerte Sona : {other}"),
    }
}

/// Envoie les alertes en attente ; renvoie le nombre d'alertes envoyées.
pub async fn flush(s: &AppState) -> Result<usize, sqlx::Error> {
    let Some(webhook) = s.cfg.discord_webhook.as_deref() else { return Ok(0) };
    let rows: Vec<(uuid::Uuid, String, Value)> =
        sqlx::query_as("select id, kind, payload from public.admin_alerts where sent_at is null order by created_at limit 20").fetch_all(&s.pool).await?;
    let mut sent = 0;
    for (id, kind, payload) in rows {
        // `allowed_mentions` vide : aucun @ ne notifie quelqu'un par accident.
        let body = json!({ "content": format_alert(&kind, &payload), "allowed_mentions": { "parse": [] } });
        match s.http.post(webhook).json(&body).send().await {
            Ok(r) if r.status().is_success() => {
                sqlx::query("update public.admin_alerts set sent_at = now() where id = $1").bind(id).execute(&s.pool).await?;
                sent += 1;
            }
            Ok(r) if r.status() == reqwest::StatusCode::TOO_MANY_REQUESTS => break,
            Ok(r) => tracing::warn!(status = %r.status(), "webhook d'alerte refusé"),
            Err(e) => {
                tracing::warn!(error = %e.without_url(), "webhook d'alerte injoignable");
                break;
            }
        }
    }
    Ok(sent)
}

pub async fn run_worker(s: AppState) {
    loop {
        if let Err(e) = flush(&s).await {
            tracing::warn!(error = %e, "alertes");
        }
        tokio::time::sleep(std::time::Duration::from_secs(20)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn messages_hold_no_personal_data() {
        let m = format_alert("new_report", &json!({ "target_type": "message", "reason": "spam", "email": "a@b.c", "details": "texte libre" }));
        assert!(m.contains("message") && m.contains("spam"));
        assert!(!m.contains("a@b.c") && !m.contains("texte libre"));
        assert!(format_alert("auto_quarantine", &json!({ "reports": 5 })).contains('5'));
        assert!(format_alert("signup_spike", &json!({ "signups_last_hour": 42 })).contains("42"));
    }
}
