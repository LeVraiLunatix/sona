mod common;
use common::{mock, Api};
use serde_json::json;

#[tokio::test]
async fn alerts_go_to_discord_once_without_personal_data() {
    let hook = mock::start(|_| (204, String::new())).await;
    let url = format!("{}/webhook", hook.url);
    let Some(api) = Api::with(move |cfg, _| cfg.discord_webhook = Some(url)).await else { return };
    let reporter = api.db.named("signaleur").await;
    let target = api.db.named("cible").await;
    api.db.x(common::Who::User(reporter), &format!("select public.create_report('profile', '{target}', null, 'harassment', 'texte libre secret@example.org')")).await.unwrap();
    assert_eq!(sona_accounts::alerts::flush(&api.state).await.unwrap(), 1);
    let seen = hook.requests();
    assert_eq!(seen.len(), 1);
    let body: serde_json::Value = serde_json::from_str(&seen[0].body).unwrap();
    assert!(body["content"].as_str().unwrap().contains("Nouveau signalement"));
    assert_eq!(body["allowed_mentions"], json!({ "parse": [] }), "aucun @ ne notifie quelqu'un");
    for secret in ["secret@example.org", "texte libre", &target.to_string(), &reporter.to_string()] {
        assert!(!seen[0].body.contains(secret), "{secret} ne doit pas partir dans l'alerte");
    }
    // Déjà envoyée : pas de doublon.
    assert_eq!(sona_accounts::alerts::flush(&api.state).await.unwrap(), 0);
    assert_eq!(hook.requests().len(), 1);
}

#[tokio::test]
async fn a_failing_webhook_keeps_the_alert_for_later() {
    let hook = mock::start(|_| (500, "boum".to_string())).await;
    let url = format!("{}/webhook", hook.url);
    let Some(api) = Api::with(move |cfg, _| cfg.discord_webhook = Some(url)).await else { return };
    api.db.su("insert into public.admin_alerts (kind, payload) values ('signup_spike', '{\"signups_last_hour\": 50}')").await;
    assert_eq!(sona_accounts::alerts::flush(&api.state).await.unwrap(), 0);
    assert_eq!(api.db.su_scalar("select count(*) from public.admin_alerts where sent_at is null").await, "1");
    // Sans webhook configuré : rien n'est envoyé ni marqué.
    let Some(none) = Api::new().await else { return };
    none.db.su("insert into public.admin_alerts (kind, payload) values ('signup_spike', '{}')").await;
    assert_eq!(sona_accounts::alerts::flush(&none.state).await.unwrap(), 0);
}
